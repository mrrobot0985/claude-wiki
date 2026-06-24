"""Tests for `kb compile`.

All LLM calls are mocked so these tests run offline and deterministically.
"""

import json
import os
import re
import threading
import time
import types
from pathlib import Path
from typing import Any

import pytest

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.cli import main
from claude_wiki.commands import compile as _compile_module  # noqa: F401
from claude_wiki.commands.compile import (
    _CHEAP_MODEL,
    _DEFAULT_SCHEMA,
    _append_compile_log,
    _apply_context_budget,
    _compile_one,
    _extract_json,
    _format_catalog_row,
    _list_existing_articles,
    _parse_compile_response,
    _read_index,
    _read_schema,
    _update_catalog,
    _write_articles,
)
from claude_wiki.errors import CompileError, WriterError
from claude_wiki.models import ProjectConfig


def _make_repo(tmpdir: str) -> tuple[Path, Path]:
    """Create a fake repo with .git, marker, and project-mode KB directory."""
    repo = Path(tmpdir) / "my-project"
    repo.mkdir()
    (repo / ".git").mkdir()

    kb_root = repo / ".claude" / "knowledge"
    marker = repo / ".claude-wiki.lock"
    marker.write_text(
        json.dumps(
            {
                "layout_version": "2",
                "repo_name": "my-project",
                "repo_owner": "owner",
                "kb_dir": "project",
                "daily_dir": "daily",
                "timezone": "UTC",
            }
        )
    )
    return repo, kb_root


def _make_fake_sdk(
    answer: str,
    capture: dict[str, Any] | None = None,
    cost: float = 0.0,
) -> tuple[types.SimpleNamespace, Any]:
    """Return a fake claude_agent_sdk namespace and an import shim."""

    class TextBlock:
        text = answer

    class AssistantMessage:
        content = [TextBlock()]

    class ResultMessage:
        total_cost_usd = cost

    class ClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    async def query(*, prompt: str, options: object) -> Any:
        if capture is not None:
            capture["prompt"] = prompt
            capture["options"] = options
        yield AssistantMessage()
        yield ResultMessage()

    fake_sdk = types.SimpleNamespace(
        AssistantMessage=AssistantMessage,
        ClaudeAgentOptions=ClaudeAgentOptions,
        ResultMessage=ResultMessage,
        TextBlock=TextBlock,
        query=query,
    )

    def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name == "claude_agent_sdk":
            return fake_sdk
        raise ImportError(name)

    return fake_sdk, fake_import


@pytest.fixture
def kb_repo(tmp_path: Path) -> tuple[Path, Path, Path, ProjectConfig]:
    """Return (repo_root, daily_log_path, kb_root, config)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    daily = repo / "daily"
    daily.mkdir()
    log = daily / "2026-06-19.md"
    log.write_text("discussed asyncio patterns and concurrency")
    kb = tmp_path / "kb"
    (kb / "concepts").mkdir(parents=True)
    config = ProjectConfig(repo_name="sdk-test")
    return repo, log, kb, config


class TestCompileCommand:
    """Offline tests for the compile subcommand."""

    def test_compile_changed_only(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """Only daily logs whose hash changed are compiled."""
        repo, kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()

        old_log = daily_dir / "2026-06-18.md"
        old_log.write_text("old content")
        new_log = daily_dir / "2026-06-19.md"
        new_log.write_text("new content")

        # Pretend the old log is already compiled.
        state_path = repo / ".claude" / "state" / "state.json"
        import hashlib

        old_hash = hashlib.sha256(old_log.read_bytes()).hexdigest()[:16]
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"ingested": {"2026-06-18.md": {"hash": old_hash}}})
        )

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile"])

        assert exit_code == 0
        compile_mock.assert_called_once()
        assert compile_mock.call_args[0][0].name == "2026-06-19.md"

        state = json.loads(state_path.read_text())
        assert "2026-06-19.md" in state["ingested"]
        assert state["ingested"]["2026-06-18.md"]["hash"] == old_hash

    def test_compile_all_forces_full_recompile(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--all`` compiles every log regardless of state."""
        repo, kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()

        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        state_path = repo / ".claude" / "state" / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "ingested": {
                        "2026-06-18.md": {"hash": "stale"},
                        "2026-06-19.md": {"hash": "stale"},
                    }
                }
            )
        )

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--all"])

        assert exit_code == 0
        assert compile_mock.call_count == 2
        compiled_names = {call.args[0].name for call in compile_mock.call_args_list}
        assert compiled_names == {"2026-06-18.md", "2026-06-19.md"}

    def test_compile_specific_file(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--file`` compiles a single log and updates state."""
        repo, kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()

        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--file", "daily/2026-06-18.md"])

        assert exit_code == 0
        compile_mock.assert_called_once()
        assert compile_mock.call_args[0][0].name == "2026-06-18.md"

        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert "2026-06-18.md" in state["ingested"]
        assert "2026-06-19.md" not in state["ingested"]

    def test_compile_dry_run_does_not_compile(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """``--dry-run`` prints targets without compiling or touching state."""
        repo, kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("new content")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch("claude_wiki.commands.compile._compile_one")

        exit_code = main(["compile", "--dry-run"])
        captured = capsys.readouterr()

        assert exit_code == 0
        compile_mock.assert_not_called()
        assert "[DRY RUN]" in captured.out
        assert "2026-06-19.md" in captured.out
        assert not (repo / ".claude" / "state" / "state.json").exists()

    def test_compile_updates_index(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """A successful compile persists articles written by the LLM in KB root."""
        repo, kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("discussed asyncio patterns")

        def fake_compile(
            log_path: Path, repo_root: Path, root: Path, config: Any, **kwargs: Any
        ) -> float:
            concept_dir = root / "concepts"
            concept_dir.mkdir(parents=True, exist_ok=True)
            concept = concept_dir / "asyncio-patterns.md"
            concept.write_text("---\ntitle: asyncio patterns\n---\n")
            catalog = root / f"{config.repo_name}.md"
            if not catalog.exists():
                catalog.write_text(
                    "# Knowledge Base Index\n\n"
                    "| Article | Summary | Compiled From | Updated |\n"
                    "|---------|---------|---------------|---------|"
                )
            content = catalog.read_text()
            content += "\n| [[concepts/asyncio-patterns]] | asyncio tips | daily/2026-06-19.md | 2026-06-19 |"
            catalog.write_text(content)
            return 0.0

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=fake_compile
        )

        exit_code = main(["compile"])

        assert exit_code == 0
        catalog_path = kb_root / "my-project.md"
        assert catalog_path.exists()
        assert "[[concepts/asyncio-patterns]]" in catalog_path.read_text()

    def test_compile_no_daily_dir(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """When the daily directory is absent, compile reports nothing to do."""
        repo, _kb_root = _make_repo(str(tmp_path))

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch("claude_wiki.commands.compile._compile_one")

        exit_code = main(["compile"])
        captured = capsys.readouterr()

        assert exit_code == 0
        compile_mock.assert_not_called()
        assert "Nothing to compile" in captured.out

    def test_compile_file_not_found(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """``--file`` referencing a missing log exits with an error."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch("claude_wiki.commands.compile._compile_one")

        exit_code = main(["compile", "--file", "daily/2026-06-99.md"])
        captured = capsys.readouterr()

        assert exit_code == 1
        compile_mock.assert_not_called()
        assert "not found" in captured.err

    def test_compile_does_not_mutate_daily_logs(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """Compilation leaves daily log content and mtime unchanged."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        log = daily_dir / "2026-06-19.md"
        log.write_text("original content")
        original_mtime = log.stat().st_mtime

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile"])

        assert exit_code == 0
        assert log.read_text() == "original content"
        assert log.stat().st_mtime == original_mtime

    def test_compile_default_exits_nonzero_on_error(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """A per-log error makes the default compile fail-fast and exit non-zero."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        monkeypatch.chdir(repo)

        def side_effect(log_path: Path, *args: Any, **kwargs: Any) -> float:
            if log_path.name == "2026-06-18.md":
                raise RuntimeError("boom")
            return 0.0

        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=side_effect
        )

        exit_code = main(["compile", "--all"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert compile_mock.call_count == 1
        assert "Error: boom" in captured.err

    def test_compile_continue_on_error_records_successes(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """--continue-on-error compiles every log, records successes, and exits non-zero if any failed."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")
        (daily_dir / "2026-06-20.md").write_text("c")

        monkeypatch.chdir(repo)

        def side_effect(log_path: Path, *args: Any, **kwargs: Any) -> float:
            if log_path.name == "2026-06-19.md":
                raise RuntimeError("mid")
            return 0.0

        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=side_effect
        )

        exit_code = main(["compile", "--all", "--continue-on-error"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert compile_mock.call_count == 3
        assert "Error: mid" in captured.err

        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert "2026-06-18.md" in state["ingested"]
        assert "2026-06-19.md" not in state["ingested"]
        assert "2026-06-20.md" in state["ingested"]

    def test_compile_continue_on_error_exits_zero_when_all_succeed(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """--continue-on-error exits zero when every log compiles successfully."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--all", "--continue-on-error"])

        assert exit_code == 0
        assert compile_mock.call_count == 2


class TestCompileMaxLogs:
    """Tests for the ``--max-logs`` / ``--limit`` cap."""

    def _make_five_pending_logs(self, tmp_path: Path) -> tuple[Path, Path]:
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        for day in range(1, 6):
            (daily_dir / f"2026-06-{day:02d}.md").write_text(f"log {day}")
        return repo, daily_dir

    def test_max_logs_respected_on_changed_only(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """The default changed-only path respects the cap and picks oldest first."""
        repo, _daily_dir = self._make_five_pending_logs(tmp_path)
        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--max-logs", "2"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert compile_mock.call_count == 2
        compiled = [call.args[0].name for call in compile_mock.call_args_list]
        assert compiled == ["2026-06-01.md", "2026-06-02.md"]
        assert "Files to compile (2 of 5 - capped by --max-logs):" in captured.out
        assert (
            "Compiled 2 of 5 pending logs. Re-run to continue (or raise --max-logs)."
            in captured.out
        )

    def test_max_logs_respected_on_all(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--all`` respects the cap and processes logs oldest-first."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        for day in range(1, 4):
            (daily_dir / f"2026-06-{day:02d}.md").write_text(f"log {day}")

        state_path = repo / ".claude" / "state" / "state.json"
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {
                    "ingested": {
                        "2026-06-01.md": {"hash": "stale"},
                        "2026-06-02.md": {"hash": "stale"},
                        "2026-06-03.md": {"hash": "stale"},
                    }
                }
            )
        )

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--all", "--max-logs", "2"])

        assert exit_code == 0
        assert compile_mock.call_count == 2
        compiled = [call.args[0].name for call in compile_mock.call_args_list]
        assert compiled == ["2026-06-01.md", "2026-06-02.md"]

    def test_max_logs_rejects_zero_and_negative(self, capsys: Any) -> None:
        """``--max-logs`` rejects 0 and negative values with a clear error."""
        for value in ("0", "-1"):
            with pytest.raises(SystemExit) as exc_info:
                main(["compile", "--max-logs", value])
            captured = capsys.readouterr()

            assert exc_info.value.code == 2
            assert f"--max-logs must be a positive integer, got {value}" in captured.err

    def test_max_logs_dry_run_honors_cap(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """``--dry-run`` lists only the capped subset and reports the total pending."""
        repo, _daily_dir = self._make_five_pending_logs(tmp_path)
        monkeypatch.chdir(repo)
        compile_mock = mocker.patch("claude_wiki.commands.compile._compile_one")

        exit_code = main(["compile", "--dry-run", "--max-logs", "2"])
        captured = capsys.readouterr()

        assert exit_code == 0
        compile_mock.assert_not_called()
        assert (
            "[DRY RUN] Would compile 2 of 5 pending logs (capped by --max-logs)."
            in captured.out
        )
        assert "2026-06-01.md" in captured.out
        assert "2026-06-02.md" in captured.out
        assert "2026-06-03.md" not in captured.out
        assert not (repo / ".claude" / "state" / "state.json").exists()

    def test_default_uncapped_regression(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """Without ``--max-logs`` all pending logs compile and no summary is printed."""
        repo, _daily_dir = self._make_five_pending_logs(tmp_path)
        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert compile_mock.call_count == 5
        assert "capped by --max-logs" not in captured.out
        assert "Compiled 5 of 5 pending logs" not in captured.out


class TestCompileGaps:
    """Cover edge cases and small helpers not exercised by the main flows."""

    def test_list_existing_articles(self, tmp_path: Path) -> None:
        """All articles under concepts/, connections/, and qa/ are loaded."""
        kb = tmp_path / "kb"
        for subdir in ("concepts", "connections", "qa"):
            (kb / subdir).mkdir(parents=True)
            (kb / subdir / f"{subdir}-x.md").write_text(f"---\ntitle: {subdir}\n---\n")

        articles = _list_existing_articles(kb)

        assert sorted(articles.keys()) == [
            "concepts/concepts-x.md",
            "connections/connections-x.md",
            "qa/qa-x.md",
        ]

    def test_read_schema_default(self, monkeypatch: Any) -> None:
        """When the package resource is unavailable, the built-in schema is used."""

        def boom(package: str) -> Any:
            raise OSError("resource unavailable")

        monkeypatch.setattr("importlib.resources.files", boom)
        schema = _read_schema()

        assert "# Knowledge Base Schema" in schema

    def test_read_index_exists_with_repo_name(self, tmp_path: Path) -> None:
        """An existing {repo_name}.md is returned verbatim."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "my-project.md").write_text("# Custom Index\n")

        assert _read_index(kb, "my-project") == "# Custom Index\n"

    def test_compile_one_mocks_sdk(self, tmp_path: Path, monkeypatch: Any) -> None:
        """`_compile_one` parses the LLM JSON response and writes via the writer."""
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Asyncio Patterns",
                        "slug": "asyncio-patterns",
                        "category": "concepts",
                        "frontmatter": 'title: "Asyncio Patterns"\nsources:\n  - "daily/2026-06-19.md"',
                        "body": "# Asyncio Patterns\n\nCore explanation.",
                    }
                ],
                "catalog_additions": [
                    {
                        "slug": "asyncio-patterns",
                        "category": "concepts",
                        "summary": "asyncio tips",
                        "compiled_from": "daily/2026-06-19.md",
                        "updated": "2026-06-19",
                    }
                ],
                "log_created": ["concepts/asyncio-patterns"],
                "log_updated": [],
            }
        )
        captured: dict[str, Any] = {}

        class TextBlock:
            text = answer

        class AssistantMessage:
            content = [TextBlock()]

        class ResultMessage:
            total_cost_usd = 0.42

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        async def query(*, prompt: str, options: object) -> Any:
            captured["prompt"] = prompt
            captured["options"] = options
            yield AssistantMessage()
            yield ResultMessage()

        fake_sdk = types.SimpleNamespace(
            AssistantMessage=AssistantMessage,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ResultMessage=ResultMessage,
            TextBlock=TextBlock,
            query=query,
        )

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "claude_agent_sdk":
                return fake_sdk
            raise ImportError(name)

        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        daily = repo / "daily"
        daily.mkdir()
        log = daily / "2026-06-19.md"
        log.write_text("discussed asyncio patterns")
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        (kb / "concepts" / "existing.md").write_text("---\ntitle: existing\n---\n")
        config = ProjectConfig(repo_name="sdk-test")

        cost = _compile_one(log, repo, kb, config)

        assert cost == 0.42
        article = kb / "concepts" / "asyncio-patterns.md"
        assert article.exists()
        assert "Asyncio Patterns" in article.read_text(encoding="utf-8")
        catalog = kb / "sdk-test.md"
        assert catalog.exists()
        catalog_text = catalog.read_text(encoding="utf-8")
        assert "[[concepts/asyncio-patterns]]" in catalog_text
        assert "daily/2026-06-19.md" in catalog_text
        log_file = kb / "log.md"
        assert log_file.exists()
        assert "compile | daily/2026-06-19.md" in log_file.read_text(encoding="utf-8")

        options = captured["options"]
        assert options.kwargs["cwd"] == str(kb)
        assert set(options.kwargs["allowed_tools"]) == {"Read", "Glob", "Grep"}
        assert "Write" not in options.kwargs["allowed_tools"]
        assert "Edit" not in options.kwargs["allowed_tools"]
        assert options.kwargs.get("permission_mode") == "dontAsk"

    def test_schema_cites_daily_logs_as_plain_text(self) -> None:
        """Daily-log citations are plain text, never [[wikilinks]] (ADR-007)."""
        assert "[[daily/" not in _DEFAULT_SCHEMA
        assert "daily/YYYY-MM-DD.md" in _DEFAULT_SCHEMA

    def test_compile_prompt_cites_daily_as_plain_text(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """The prompt sent to the compiler contains no [[daily/…]] example wikilinks."""
        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )

        class TextBlock:
            text = answer

        class AssistantMessage:
            content = [TextBlock()]

        class ResultMessage:
            total_cost_usd = 0.0

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        captured: dict[str, Any] = {}

        async def query(*, prompt: str, options: object) -> Any:
            captured["prompt"] = prompt
            captured["options"] = options
            yield AssistantMessage()
            yield ResultMessage()

        fake_sdk = types.SimpleNamespace(
            AssistantMessage=AssistantMessage,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ResultMessage=ResultMessage,
            TextBlock=TextBlock,
            query=query,
        )

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "claude_agent_sdk":
                return fake_sdk
            raise ImportError(name)

        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        daily = repo / "daily"
        daily.mkdir()
        log = daily / "2026-06-19.md"
        log.write_text("discussed asyncio patterns")
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        config = ProjectConfig(repo_name="sdk-test")

        _compile_one(log, repo, kb, config)

        prompt = captured["prompt"]
        # The example citation is plain text; no [[daily/YYYY-MM-DD.md]] example.
        assert "[[daily/YYYY-MM-DD.md]]" not in prompt
        assert "daily/2026-06-19.md" in prompt
        assert "- daily/YYYY-MM-DD.md" in prompt

        options = captured["options"]
        assert options.kwargs["cwd"] == str(kb)
        assert set(options.kwargs["allowed_tools"]) == {"Read", "Glob", "Grep"}
        assert "Write" not in options.kwargs["allowed_tools"]
        assert "Edit" not in options.kwargs["allowed_tools"]
        assert options.kwargs.get("permission_mode") == "dontAsk"

    def test_compile_file_absolute_path(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--file`` accepts an absolute path to a daily log."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        log = daily_dir / "2026-06-19.md"
        log.write_text("x")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--file", str(log.resolve())])

        assert exit_code == 0
        compile_mock.assert_called_once()
        assert compile_mock.call_args[0][0].name == "2026-06-19.md"

    def test_compile_file_repo_relative_path(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--file`` falls back to resolving the path from the repo root."""
        repo, _kb_root = _make_repo(str(tmp_path))
        logs_dir = repo / "logs"
        logs_dir.mkdir()
        log = logs_dir / "2026-06-19.md"
        log.write_text("x")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--file", "logs/2026-06-19.md"])

        assert exit_code == 0
        compile_mock.assert_called_once()
        assert compile_mock.call_args[0][0].name == "2026-06-19.md"

    def test_compile_outside_git_repo(self, tmp_path: Path, capsys: Any) -> None:
        """Running compile outside a git repository prints an error."""
        exit_code = main(["compile", "--path", str(tmp_path / "not-a-repo")])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Not in a git repository." in captured.err


class TestCompilePerformance:
    """Regression tests for the O(n²) file-read fixes."""

    def test_compile_reads_index_and_articles_once(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """The index and existing articles are read once per compile run."""
        repo, kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("log a")
        (daily_dir / "2026-06-19.md").write_text("log b")

        (kb_root / "concepts").mkdir(parents=True)
        (kb_root / "concepts" / "existing.md").write_text("---\ntitle: existing\n---\n")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)
        read_index_spy = mocker.patch(
            "claude_wiki.commands.compile._read_index", return_value="# Index"
        )
        list_articles_spy = mocker.patch(
            "claude_wiki.commands.compile._list_existing_articles", return_value={}
        )

        exit_code = main(["compile", "--all"])

        assert exit_code == 0
        read_index_spy.assert_called_once()
        list_articles_spy.assert_called_once()


class TestCompileStateAndFailureReporting:
    """State I/O robustness and honest failure reporting."""

    def test_corrupt_state_recovers_as_fresh(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """A corrupt state.json is treated as fresh instead of crashing."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")

        state_dir = repo / ".claude" / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text("{not valid json")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile", "--all"])
        assert exit_code == 0
        state = json.loads((state_dir / "state.json").read_text())
        assert "2026-06-18.md" in state["ingested"]

    def test_failure_does_not_stamp_registry_or_claim_complete(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """A failing compile must not update last_compiled or print 'complete'."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=RuntimeError("boom"),
        )
        register_mock = mocker.patch(
            "claude_wiki.commands.compile.GlobalIndexManager.register"
        )

        exit_code = main(["compile", "--all"])
        captured = capsys.readouterr()

        assert exit_code == 1
        register_mock.assert_not_called()
        assert "Compilation complete" not in captured.out
        assert "Compilation failed" in captured.err

    def test_success_stamps_registry(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """A successful compile updates the global registry."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)
        mocker.patch(
            "claude_wiki.commands.compile.GlobalIndexManager.count_articles",
            return_value=0,
        )
        register_mock = mocker.patch(
            "claude_wiki.commands.compile.GlobalIndexManager.register"
        )

        exit_code = main(["compile", "--all"])
        assert exit_code == 0
        register_mock.assert_called_once()

    def test_state_written_atomically_without_temp_leftover(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """A successful compile leaves valid state.json and no .tmp sibling."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        main(["compile", "--all"])

        state_dir = repo / ".claude" / "state"
        state_file = state_dir / "state.json"
        assert state_file.exists()
        json.loads(state_file.read_text())  # valid JSON
        assert not (state_dir / "state.json.tmp").exists()


class TestCompileWriterIntegration:
    """ADR-012: compile writes come from Python, not from the LLM's tools."""

    @staticmethod
    def _fake_sdk(
        answer: str,
        capture: dict[str, Any] | None = None,
        cost: float = 0.0,
    ) -> tuple[types.SimpleNamespace, Any]:
        """Return a fake SDK namespace and an import shim."""

        class TextBlock:
            text = answer

        class AssistantMessage:
            content = [TextBlock()]

        class ResultMessage:
            total_cost_usd = cost

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        async def query(*, prompt: str, options: object) -> Any:
            if capture is not None:
                capture["prompt"] = prompt
                capture["options"] = options
            yield AssistantMessage()
            yield ResultMessage()

        fake_sdk = types.SimpleNamespace(
            AssistantMessage=AssistantMessage,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ResultMessage=ResultMessage,
            TextBlock=TextBlock,
            query=query,
        )

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "claude_agent_sdk":
                return fake_sdk
            raise ImportError(name)

        return fake_sdk, fake_import

    @pytest.fixture
    def kb_repo(self, tmp_path: Path) -> tuple[Path, Path, Path, ProjectConfig]:
        """Return (repo_root, daily_log_path, kb_root, config)."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        daily = repo / "daily"
        daily.mkdir()
        log = daily / "2026-06-19.md"
        log.write_text("discussed asyncio patterns and concurrency")
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        config = ProjectConfig(repo_name="sdk-test")
        return repo, log, kb, config

    def test_compile_writes_articles_and_updates_catalog_and_log(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A valid JSON response writes articles, catalog rows, and a log entry."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Asyncio Patterns",
                        "slug": "asyncio-patterns",
                        "category": "concepts",
                        "frontmatter": 'title: "Asyncio Patterns"',
                        "body": "# Asyncio Patterns\n\nCore idea.",
                    },
                    {
                        "title": "Concurrency Primitives",
                        "slug": "concurrency-primitives",
                        "category": "concepts",
                        "frontmatter": 'title: "Concurrency Primitives"',
                        "body": "# Concurrency Primitives\n\nDetails.",
                    },
                ],
                "catalog_additions": [
                    {
                        "slug": "asyncio-patterns",
                        "category": "concepts",
                        "summary": "asyncio overview",
                        "compiled_from": "daily/2026-06-19.md",
                        "updated": "2026-06-19",
                    },
                    {
                        "slug": "concurrency-primitives",
                        "category": "concepts",
                        "summary": "concurrency tools",
                        "compiled_from": "daily/2026-06-19.md",
                        "updated": "2026-06-19",
                    },
                ],
                "log_created": [
                    "concepts/asyncio-patterns",
                    "concepts/concurrency-primitives",
                ],
                "log_updated": [],
            }
        )
        _fake_sdk, fake_import = self._fake_sdk(answer)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        cost = _compile_one(log, repo, kb, config)

        assert cost == 0.0
        assert (kb / "concepts" / "asyncio-patterns.md").exists()
        assert (kb / "concepts" / "concurrency-primitives.md").exists()
        catalog = kb / "sdk-test.md"
        catalog_text = catalog.read_text(encoding="utf-8")
        assert "[[concepts/asyncio-patterns]]" in catalog_text
        assert "[[concepts/concurrency-primitives]]" in catalog_text
        log_file = kb / "log.md"
        assert log_file.exists()
        assert "compile | daily/2026-06-19.md" in log_file.read_text(encoding="utf-8")

    def test_compile_rejects_malformed_json(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A response with no parseable JSON fails the log fast."""
        repo, log, kb, config = kb_repo
        _fake_sdk, fake_import = self._fake_sdk("{bad}")
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(WriterError, match="malformed JSON"):
            _compile_one(log, repo, kb, config)

        assert not list((kb / "concepts").glob("*.md"))
        assert not (kb / "sdk-test.md").exists()
        assert not (kb / "log.md").exists()

    def test_compile_rejects_bad_slug(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """An article with an invalid slug fails before anything is written."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Good",
                        "slug": "good-article",
                        "category": "concepts",
                        "frontmatter": "title: Good",
                        "body": "# Good\n\nBody.",
                    },
                    {
                        "title": "Bad Slug",
                        "slug": "bad slug!",
                        "category": "concepts",
                        "frontmatter": "title: Bad",
                        "body": "# Bad\n\nBody.",
                    },
                ],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        _fake_sdk, fake_import = self._fake_sdk(answer)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(WriterError, match="invalid"):
            _compile_one(log, repo, kb, config)

        assert not (kb / "concepts" / "good-article.md").exists()
        assert not (kb / "concepts" / "bad-slug.md").exists()

    def test_compile_rejects_bad_category(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """An article with a category outside the allowed set fails fast."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Bad",
                        "slug": "bad",
                        "category": "misc",
                        "frontmatter": "title: Bad",
                        "body": "# Bad\n\nBody.",
                    }
                ],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        _fake_sdk, fake_import = self._fake_sdk(answer)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(WriterError, match="category"):
            _compile_one(log, repo, kb, config)

        assert not (kb / "misc").exists()
        assert not (kb / "concepts" / "bad.md").exists()

    def test_compile_rejects_path_traversal_slug(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A slug containing traversal sequences is rejected before writing."""
        repo, log, kb, config = kb_repo
        outside = tmp_path / "outside"
        outside.mkdir()
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Evil",
                        "slug": "../../outside/evil",
                        "category": "concepts",
                        "frontmatter": "title: Evil",
                        "body": "# Evil\n\nBody.",
                    }
                ],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        _fake_sdk, fake_import = self._fake_sdk(answer)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(WriterError):
            _compile_one(log, repo, kb, config)

        assert not list(outside.glob("*.md"))

    def test_compile_rejects_invalid_catalog_addition(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A valid article but an invalid catalog row must not write anything."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Good",
                        "slug": "good-article",
                        "category": "concepts",
                        "frontmatter": "title: Good",
                        "body": "# Good\n\nBody.",
                    }
                ],
                "catalog_additions": [
                    {
                        "slug": "good-article",
                        "category": "bad-category",
                        "summary": "summary",
                    }
                ],
                "log_created": ["good-article"],
                "log_updated": [],
            }
        )
        _fake_sdk, fake_import = self._fake_sdk(answer)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(WriterError, match="category"):
            _compile_one(log, repo, kb, config)

        assert not (kb / "concepts" / "good-article.md").exists()
        assert not (kb / "sdk-test.md").exists()
        assert not (kb / "log.md").exists()

    def test_compile_continue_on_error_records_failed_log(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        mocker: Any,
    ) -> None:
        """``--continue-on-error`` marks a log failed when the LLM JSON is bad."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        def side_effect(log_path: Path, *args: Any, **kwargs: Any) -> float:
            if log_path.name == "2026-06-19.md":
                raise WriterError("bad json")
            return 0.0

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=side_effect
        )

        exit_code = main(["compile", "--all", "--continue-on-error"])

        assert exit_code == 1
        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert "2026-06-18.md" in state["ingested"]
        assert "2026-06-19.md" not in state["ingested"]

    def test_compile_all_or_nothing_for_valid_articles(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """All articles are validated before any write; a bad article writes nothing."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "First",
                        "slug": "first",
                        "category": "concepts",
                        "frontmatter": "title: First",
                        "body": "# First\n\nBody.",
                    },
                    {
                        "title": "",
                        "slug": "",
                        "category": "concepts",
                        "frontmatter": "title: Second",
                        "body": "# Second\n\nBody.",
                    },
                ],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        _fake_sdk, fake_import = self._fake_sdk(answer)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(WriterError):
            _compile_one(log, repo, kb, config)

        assert not (kb / "concepts" / "first.md").exists()


class TestCompileSecurity:
    """Critic-identified integrity/escape defects in compile.py."""

    def test_catalog_update_anchors_link_not_substring(self, tmp_path: Path) -> None:
        """Only the row for the article column is replaced; citing rows stay."""
        kb = tmp_path / "kb"
        kb.mkdir()
        catalog = kb / "repo-name.md"
        catalog.write_text(
            "# repo-name Knowledge Base\n\n"
            "| Article | Summary | Compiled From | Updated |\n"
            "|---|---|---|---|\n"
            "| [[concepts/foo]] | old summary | daily/2026-06-18.md | 2026-06-18 |\n"
            "| [[concepts/bar]] | see [[concepts/foo]] for more | daily/2026-06-18.md | 2026-06-18 |"
        )
        addition = {
            "slug": "foo",
            "category": "concepts",
            "summary": "new summary",
            "compiled_from": "daily/2026-06-19.md",
            "updated": "2026-06-19",
        }

        _update_catalog(kb, "repo-name", [addition], "2026-06-19.md", "2026-06-19")

        lines = catalog.read_text(encoding="utf-8").splitlines()
        assert any(
            line
            == "| [[concepts/foo]] | new summary | daily/2026-06-19.md | 2026-06-19 |"
            for line in lines
        )
        assert any(
            line
            == "| [[concepts/bar]] | see [[concepts/foo]] for more | daily/2026-06-18.md | 2026-06-18 |"
            for line in lines
        )

    def test_catalog_row_sanitizes_all_fields(self) -> None:
        """Injection characters in any table field become a single safe row."""
        addition = {
            "slug": "foo",
            "category": "concepts",
            "summary": "one\nline\rsummary",
            "compiled_from": "daily/2026-06-19.md|extra|column",
            "updated": "2026-06-19\n",
        }
        row = _format_catalog_row(addition, "2026-06-19.md", "2026-06-19")
        assert row.count("|") == 5  # 4 columns + outer table delimiters
        assert "\n" not in row
        assert "\r" not in row
        assert "daily/2026-06-19.md|extra|column" not in row
        assert "daily/2026-06-19.md extra column" in row

    def test_compile_log_rejects_malicious_ref(self, tmp_path: Path) -> None:
        """A crafted log ref is rejected before any write, leaving KB untouched."""
        kb = tmp_path / "kb"
        kb.mkdir()
        log_path = tmp_path / "daily" / "2026-06-19.md"
        log_path.parent.mkdir(parents=True)
        log_path.write_text("log content")

        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Good Article",
                        "slug": "good-article",
                        "category": "concepts",
                        "frontmatter": "title: Good Article\ncreated: 2026-06-19\nupdated: 2026-06-19",
                        "body": "# Good Article\n\nContent.",
                    }
                ],
                "catalog_additions": [
                    {
                        "slug": "good-article",
                        "category": "concepts",
                        "summary": "summary",
                        "compiled_from": "daily/2026-06-19.md",
                        "updated": "2026-06-19",
                    }
                ],
                "log_created": ["concepts/foo]]\n## injected\n- [[malicious"],
                "log_updated": [],
            }
        )

        with pytest.raises(WriterError, match="log_created"):
            (
                articles,
                catalog_additions,
                log_created,
                log_updated,
            ) = _parse_compile_response(answer)
            _write_articles(articles, kb)
            _update_catalog(
                kb, "my-project", catalog_additions, log_path.name, log_path.stem
            )
            _append_compile_log(kb, log_path, log_created, log_updated)

        assert not (kb / "log.md").exists()
        assert not (kb / "concepts" / "good-article.md").exists()
        assert not resolve_catalog(kb, "my-project").exists()

    def test_parse_compile_response_rejects_non_string_catalog_fields(
        self, tmp_path: Path
    ) -> None:
        """A catalog addition with non-string fields raises WriterError fast."""
        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [
                    {
                        "slug": 123,
                        "category": "concepts",
                        "summary": "summary",
                        "compiled_from": "daily/2026-06-19.md",
                        "updated": "2026-06-19",
                    }
                ],
                "log_created": [],
                "log_updated": [],
            }
        )

        with pytest.raises(WriterError, match="must be strings"):
            _parse_compile_response(answer)

    def test_update_catalog_rejects_symlinked_catalog(
        self,
        tmp_path: Path,
    ) -> None:
        """A catalog file symlinked outside kb_root is rejected before reading."""
        outside = tmp_path / "outside"
        outside.mkdir()
        outside_catalog = outside / "stolen.md"
        outside_catalog.write_text("# Stolen Catalog\n")
        kb = tmp_path / "kb"
        kb.mkdir()
        os.symlink(outside_catalog, kb / "repo-name.md")

        addition = {
            "slug": "foo",
            "category": "concepts",
            "summary": "summary",
            "compiled_from": "daily/2026-06-19.md",
            "updated": "2026-06-19",
        }

        with pytest.raises(WriterError):
            _update_catalog(kb, "repo-name", [addition], "2026-06-19.md", "2026-06-19")

        assert outside_catalog.read_text(encoding="utf-8") == "# Stolen Catalog\n"

    def test_permission_mode_is_dontask_not_accept_edits(
        self,
        tmp_path: Path,
        monkeypatch: Any,
    ) -> None:
        """Compile SDK options explicitly set permission_mode='dontAsk'."""
        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )

        class TextBlock:
            text = answer

        class AssistantMessage:
            content = [TextBlock()]

        class ResultMessage:
            total_cost_usd = 0.0

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: Any) -> None:
                self.kwargs = kwargs

        captured: dict[str, Any] = {}

        async def query(*, prompt: str, options: object) -> Any:
            captured["options"] = options
            yield AssistantMessage()
            yield ResultMessage()

        fake_sdk = types.SimpleNamespace(
            AssistantMessage=AssistantMessage,
            ClaudeAgentOptions=ClaudeAgentOptions,
            ResultMessage=ResultMessage,
            TextBlock=TextBlock,
            query=query,
        )

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "claude_agent_sdk":
                return fake_sdk
            raise ImportError(name)

        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        daily = repo / "daily"
        daily.mkdir()
        log = daily / "2026-06-19.md"
        log.write_text("discussed asyncio patterns")
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        config = ProjectConfig(repo_name="sdk-test")

        _compile_one(log, repo, kb, config)

        options = captured["options"]
        assert options.kwargs["permission_mode"] == "dontAsk"
        assert options.kwargs["permission_mode"] != "acceptEdits"


class TestCompileContextBudget:
    """ADR-011: existing-article context budget with hub-weighted eviction."""

    def test_context_budget_computes_inbound_from_memory(
        self, tmp_path: Path, monkeypatch: Any, mocker: Any
    ) -> None:
        """Inbound counts come from the articles dict, not a fresh disk read."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        a = kb / "concepts" / "a.md"
        a.write_text("[[concepts/b]]")
        b = kb / "concepts" / "b.md"
        b.write_text("content")
        # Make a the newest; only hub classification would select b first.
        now = time.time()
        os.utime(a, (now, now))
        os.utime(b, (now - 1, now - 1))

        articles = _list_existing_articles(kb)
        build_graph_spy = mocker.patch(
            "claude_wiki.graph_utils.build_link_graph",
            side_effect=RuntimeError("disk read"),
        )
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 12)

        selected = _apply_context_budget(kb, articles)

        build_graph_spy.assert_not_called()
        assert "concepts/b.md" in selected
        assert "concepts/a.md" not in selected

    def test_context_budget_keeps_all_when_under_budget(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Articles under the budget are all included."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        (kb / "concepts" / "a.md").write_text("x" * 500)
        (kb / "concepts" / "b.md").write_text("y" * 500)

        articles = _list_existing_articles(kb)
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 2000)
        selected = _apply_context_budget(kb, articles)

        assert sorted(selected.keys()) == sorted(articles.keys())

    def test_context_budget_evicts_oldest_non_hubs_first(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Hubs are kept; oldest non-hubs are evicted first when over budget."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)

        old_nonhub = kb / "concepts" / "old-nonhub.md"
        old_nonhub.write_text("old " * 500)  # 2000 chars
        old_mtime = time.time() - 86400
        os.utime(old_nonhub, (old_mtime, old_mtime))

        hub = kb / "concepts" / "hub.md"
        hub.write_text("hub " * 500)  # 2000 chars

        # linker makes hub a hub (one inbound link).
        linker = kb / "concepts" / "linker.md"
        linker.write_text("See [[concepts/hub]].")

        articles = _list_existing_articles(kb)
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 2500)
        selected = _apply_context_budget(kb, articles)

        assert "concepts/hub.md" in selected
        assert "concepts/old-nonhub.md" not in selected

    def test_context_budget_zero_inbound_evicted_while_hub_kept(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A zero-inbound article is a non-hub and is evicted before a hub."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)

        hub = kb / "concepts" / "hub.md"
        hub.write_text("hub " * 1500)  # 6000 chars
        linker = kb / "concepts" / "linker.md"
        linker.write_text("[[concepts/hub]]")  # hub gets 1 inbound

        zero = kb / "concepts" / "zero.md"
        zero.write_text("zero " * 1500)  # 6000 chars, oldest
        old_mtime = time.time() - 86400
        os.utime(zero, (old_mtime, old_mtime))

        articles = _list_existing_articles(kb)
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 7000)
        selected = _apply_context_budget(kb, articles)

        assert "concepts/hub.md" in selected
        assert "concepts/zero.md" not in selected

    def test_context_budget_ties_at_median_are_hubs(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """Articles tied at the median inbound count are classified as hubs."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)

        a = kb / "concepts" / "a.md"
        a.write_text("a " * 1500)  # 3000 chars
        b = kb / "concepts" / "b.md"
        b.write_text("b " * 1500)  # 3000 chars
        # Two inbound links each so a and b share the median of [2, 2].
        (kb / "concepts" / "linker-a1.md").write_text("[[concepts/a]]")
        (kb / "concepts" / "linker-a2.md").write_text("[[concepts/a]]")
        (kb / "concepts" / "linker-b1.md").write_text("[[concepts/b]]")
        (kb / "concepts" / "linker-b2.md").write_text("[[concepts/b]]")

        zero = kb / "concepts" / "zero.md"
        zero.write_text("z " * 1500)  # 3000 chars

        articles = _list_existing_articles(kb)
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 6500)
        selected = _apply_context_budget(kb, articles)

        assert "concepts/a.md" in selected
        assert "concepts/b.md" in selected
        assert "concepts/zero.md" not in selected

    def test_context_budget_single_positive_inbound_is_hub(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """A lone article with a positive inbound count is treated as a hub."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)

        target = kb / "concepts" / "target.md"
        target.write_text("target " * 1500)  # 9000 chars
        linker = kb / "concepts" / "linker.md"
        linker.write_text("[[concepts/target]]")  # target gets 1 inbound

        zero = kb / "concepts" / "zero.md"
        zero.write_text("zero " * 1500)  # 6000 chars

        articles = _list_existing_articles(kb)
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 9500)
        selected = _apply_context_budget(kb, articles)

        assert "concepts/target.md" in selected
        assert "concepts/zero.md" not in selected

    def test_context_budget_includes_catalog_separately(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A huge catalog does not push articles out of the budget."""
        repo, log, kb, config = kb_repo
        (kb / "concepts" / "existing.md").write_text("existing body")
        (kb / f"{config.repo_name}.md").write_text("catalog " * 10_000)

        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        captured: dict[str, Any] = {}
        fake_sdk, fake_import = _make_fake_sdk(answer, capture=captured)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)
        monkeypatch.setattr(_compile_module, "_CONTEXT_BUDGET_CHARS", 100)
        monkeypatch.setattr(_compile_module, "_TOKEN_ESTIMATE_THRESHOLD", 100_000)

        _compile_one(log, repo, kb, config)

        prompt = captured["prompt"]
        assert "existing body" in prompt


class TestCompileCostCap:
    """ADR-011: per-log USD cap records cost and skips writes/registry on failure."""

    def test_per_log_usd_cap_raises_before_writing(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A cost above the cap raises CompileError with the cost attached."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [
                    {
                        "title": "Should Not Write",
                        "slug": "should-not-write",
                        "category": "concepts",
                        "frontmatter": "title: Should Not Write",
                        "body": "# Should Not Write\n\nBody.",
                    }
                ],
                "catalog_additions": [],
                "log_created": ["concepts/should-not-write"],
                "log_updated": [],
            }
        )
        fake_sdk, fake_import = _make_fake_sdk(answer, cost=1.00)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)
        monkeypatch.setattr(_compile_module, "_PER_LOG_USD_CAP", 0.10)

        with pytest.raises(CompileError) as exc_info:
            _compile_one(log, repo, kb, config)

        assert exc_info.value.cost_usd == 1.00
        assert "0.10" in str(exc_info.value)
        assert not (kb / "concepts" / "should-not-write.md").exists()
        assert not (kb / "log.md").exists()

    def test_per_log_usd_cap_records_cost_and_skips_registry(
        self,
        monkeypatch: Any,
        tmp_path: Path,
        mocker: Any,
        capsys: Any,
    ) -> None:
        """CLI records the failed log's cost and does not stamp the registry."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("a")

        monkeypatch.chdir(repo)

        def side_effect(log_path: Path, *args: Any, **kwargs: Any) -> float:
            raise CompileError("cap exceeded", cost_usd=0.99)

        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=side_effect
        )
        register_mock = mocker.patch(
            "claude_wiki.commands.compile.GlobalIndexManager.register"
        )

        exit_code = main(["compile", "--all"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "cap exceeded" in captured.err
        register_mock.assert_not_called()

        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert state["ingested"]["2026-06-19.md"]["cost_usd"] == 0.99
        assert state["ingested"]["2026-06-19.md"]["failed"] is True
        assert state["total_cost"] == 0.99

    def test_per_log_usd_cap_respects_continue_on_error(
        self,
        monkeypatch: Any,
        tmp_path: Path,
        mocker: Any,
    ) -> None:
        """--continue-on-error records capped costs and keeps compiling."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        monkeypatch.chdir(repo)

        def side_effect(log_path: Path, *args: Any, **kwargs: Any) -> float:
            if log_path.name == "2026-06-18.md":
                raise CompileError("cap", cost_usd=0.50)
            return 0.25

        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=side_effect
        )

        exit_code = main(["compile", "--all", "--continue-on-error"])

        assert exit_code == 1
        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert state["ingested"]["2026-06-18.md"]["cost_usd"] == 0.50
        assert state["ingested"]["2026-06-18.md"]["failed"] is True
        assert state["ingested"]["2026-06-19.md"]["cost_usd"] == 0.25
        assert "failed" not in state["ingested"]["2026-06-19.md"]
        assert state["total_cost"] == 0.75


class TestCompileTokenGuard:
    """ADR-011: reject obviously oversized prompts before spending."""

    def test_token_guard_raises_before_llm_call(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """An estimated token count above the threshold aborts before query()."""
        repo, log, kb, config = kb_repo

        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        calls: list[str] = []

        fake_sdk, fake_import = _make_fake_sdk(answer)
        original_query = fake_sdk.query

        async def query(*, prompt: str, options: object) -> Any:
            calls.append(prompt)
            async for message in original_query(prompt=prompt, options=options):
                yield message

        fake_sdk.query = query
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)
        monkeypatch.setattr(_compile_module, "_TOKEN_ESTIMATE_THRESHOLD", 1)

        with pytest.raises(CompileError, match="token guard"):
            _compile_one(log, repo, kb, config)

        assert not calls


class TestCompileModelSelection:
    """ADR-011: --model and --cheap opt-in model selection."""

    def test_model_arg_passed_to_sdk(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A non-empty model argument is forwarded to ClaudeAgentOptions."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        captured: dict[str, Any] = {}
        fake_sdk, fake_import = _make_fake_sdk(answer, capture=captured)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        _compile_one(log, repo, kb, config, model="claude-test-model")

        assert captured["options"].kwargs.get("model") == "claude-test-model"

    def test_default_model_not_set(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """When no model is requested, options do not include a model key."""
        repo, log, kb, config = kb_repo
        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        captured: dict[str, Any] = {}
        fake_sdk, fake_import = _make_fake_sdk(answer, capture=captured)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        _compile_one(log, repo, kb, config)

        assert "model" not in captured["options"].kwargs

    def test_cheap_flag_sets_model_and_warns(
        self,
        monkeypatch: Any,
        tmp_path: Path,
        mocker: Any,
        capsys: Any,
    ) -> None:
        """--cheap uses the cheaper model and prints a quality warning."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("a")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--cheap"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert compile_mock.call_count == 1
        assert compile_mock.call_args.kwargs.get("model") == _CHEAP_MODEL
        assert "cheaper model" in captured.err
        assert _CHEAP_MODEL in captured.err

    def test_cheap_overrides_explicit_model(
        self,
        monkeypatch: Any,
        tmp_path: Path,
        mocker: Any,
        capsys: Any,
    ) -> None:
        """--cheap wins over --model with an override warning."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("a")

        monkeypatch.chdir(repo)
        compile_mock = mocker.patch(
            "claude_wiki.commands.compile._compile_one", return_value=0.0
        )

        exit_code = main(["compile", "--model", "custom", "--cheap"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert compile_mock.call_args.kwargs.get("model") == _CHEAP_MODEL
        assert "overrides" in captured.err

    def test_invalid_model_rejected_before_sdk_call(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """A model string that does not match the claude-* pattern is rejected."""
        repo, log, kb, config = kb_repo

        fake_sdk = types.SimpleNamespace(
            AssistantMessage=object,
            ClaudeAgentOptions=object,
            ResultMessage=object,
            query=lambda **kwargs: iter([]),
        )

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "claude_agent_sdk":
                return fake_sdk
            raise ImportError(name)

        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        with pytest.raises(CompileError, match="Invalid model"):
            _compile_one(log, repo, kb, config, model="gpt-4")


class TestCompileJsonExtraction:
    """ADR-012: robust extraction of the JSON object from LLM responses."""

    def test_extract_json_prefers_fenced_block(self) -> None:
        """A fenced ```json block is extracted before any surrounding prose."""
        raw = (
            'Some prose with {"unfenced": true}\n'
            "```json\n"
            '{"articles": [], "catalog_additions": []}\n'
            "```\n"
            "more prose"
        )
        result = _extract_json(raw)
        assert result == '{"articles": [], "catalog_additions": []}'

    def test_extract_json_finds_object_after_prose(self) -> None:
        """Brace-depth fallback locates the JSON object after leading prose."""
        raw = 'Here is the result: {"articles": []} thanks!'
        result = _extract_json(raw)
        assert result == '{"articles": []}'

    def test_extract_json_ignores_braces_inside_strings(self) -> None:
        """Braces inside JSON string values do not confuse brace-depth parsing."""
        raw = '{"body": "A { brace and a } brace"}'
        result = _extract_json(raw)
        assert result == '{"body": "A { brace and a } brace"}'

    def test_extract_json_rejects_unclosed_object(self) -> None:
        """An unclosed JSON object raises a clear WriterError."""
        with pytest.raises(WriterError, match="unclosed JSON object"):
            _extract_json('{"articles": [')


class TestCompilePromptEscaping:
    """ADR-012: existing article content must not break prompt code fences."""

    def test_triple_backticks_in_article_use_longer_fence(
        self,
        tmp_path: Path,
        monkeypatch: Any,
        kb_repo: tuple[Path, Path, Path, ProjectConfig],
    ) -> None:
        """Article content containing ``` is wrapped in a fence longer than that run."""
        repo, log, kb, config = kb_repo
        (kb / "concepts" / "existing.md").write_text("```python\nprint('hello')\n```")
        answer = json.dumps(
            {
                "articles": [],
                "catalog_additions": [],
                "log_created": [],
                "log_updated": [],
            }
        )
        captured: dict[str, Any] = {}
        fake_sdk, fake_import = _make_fake_sdk(answer, capture=captured)
        monkeypatch.setattr(_compile_module.importlib, "import_module", fake_import)

        _compile_one(log, repo, kb, config)

        prompt = captured["prompt"]
        # The article fence must use more than 3 backticks to avoid being closed by content.
        assert "```python" in prompt
        assert "````markdown" in prompt
        # The content should not split the prompt article section into multiple blocks.
        article_section = prompt[prompt.find("### concepts/existing.md") :]
        fence_runs = sorted(
            {len(m) for m in re.findall(r"`+", article_section)}, reverse=True
        )
        # The longest backtick run in the section belongs to the outer fence.
        assert fence_runs[0] > 3


class TestCompileStateLock:
    """ADR-013: advisory fcntl lock around state.json RMW."""

    def test_concurrent_compiles_do_not_clobber_state(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        mocker: Any,
    ) -> None:
        """Two concurrent compiles of different files keep both state entries."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")
        (daily_dir / "2026-06-19.md").write_text("b")

        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.25)

        barrier = threading.Barrier(2)
        exceptions: list[BaseException] = []

        thread_lock = threading.Lock()

        def fake_lockf(_fd: int, operation: int, *_args: Any, **_kwargs: Any) -> None:
            if operation == _compile_module.fcntl.LOCK_UN:
                thread_lock.release()
                return
            if not thread_lock.acquire(blocking=False):
                raise BlockingIOError("lock busy")

        monkeypatch.setattr(_compile_module.fcntl, "lockf", fake_lockf)

        def compile_file(file_arg: str) -> None:
            barrier.wait()
            try:
                exit_code = main(["compile", "--path", str(repo), "--file", file_arg])
                if exit_code != 0:
                    raise AssertionError(f"compile exited {exit_code}")
            except BaseException as e:
                exceptions.append(e)

        t1 = threading.Thread(target=compile_file, args=("daily/2026-06-18.md",))
        t2 = threading.Thread(target=compile_file, args=("daily/2026-06-19.md",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not exceptions
        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert "2026-06-18.md" in state["ingested"]
        assert "2026-06-19.md" in state["ingested"]
        assert state["total_cost"] == 0.5

    def test_state_lock_timeout_raises_timeout_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """If the state lock cannot be acquired, a TimeoutError is raised."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")

        def busy_on_acquire(
            _fd: int, operation: int, *_args: Any, **_kwargs: Any
        ) -> None:
            if operation == _compile_module.fcntl.LOCK_UN:
                return
            raise BlockingIOError("lock busy")

        monkeypatch.setattr(_compile_module.fcntl, "lockf", busy_on_acquire)
        monkeypatch.setattr(_compile_module, "_STATE_LOCK_RETRIES", 3)
        monkeypatch.setattr(_compile_module, "_STATE_LOCK_RETRY_INTERVAL", 0.01)

        with pytest.raises(TimeoutError, match="timed out acquiring state lock"):
            main(["compile", "--path", str(repo), "--all"])

    def test_windows_platform_skips_state_lock(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        mocker: Any,
    ) -> None:
        """On Windows the lock context manager is a no-op but compile still succeeds."""
        repo, _kb_root = _make_repo(str(tmp_path))
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-18.md").write_text("a")

        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)
        mocker.patch("claude_wiki.commands.compile.GlobalIndexManager.register")

        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        if getattr(_compile_module, "fcntl", None) is not None:
            original_lockf = _compile_module.fcntl.lockf

            def capture_lockf(*args: Any, **kwargs: Any) -> None:
                calls.append((args, kwargs))
                return original_lockf(*args, **kwargs)

            monkeypatch.setattr(_compile_module.fcntl, "lockf", capture_lockf)
        monkeypatch.setattr(_compile_module.sys, "platform", "win32")

        exit_code = main(["compile", "--path", str(repo)])

        assert exit_code == 0
        state = json.loads((repo / ".claude" / "state" / "state.json").read_text())
        assert "2026-06-18.md" in state["ingested"]
        assert not calls
