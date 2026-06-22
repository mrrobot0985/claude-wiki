"""Tests for `kb compile`.

All LLM calls are mocked so these tests run offline and deterministically.
"""

import json
import types
from pathlib import Path
from typing import Any

import pytest

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.cli import main
from claude_wiki.commands import compile as _compile_module  # noqa: F401
from claude_wiki.commands.compile import (
    _DEFAULT_SCHEMA,
    _append_compile_log,
    _compile_one,
    _format_catalog_row,
    _list_existing_articles,
    _parse_compile_response,
    _read_index,
    _read_schema,
    _update_catalog,
    _write_articles,
)
from claude_wiki.errors import WriterError
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
                "repo_name": "my-project",
                "repo_owner": "owner",
                "kb_dir": "project",
                "daily_dir": "daily",
                "timezone": "UTC",
            }
        )
    )
    return repo, kb_root


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
            log_path: Path, repo_root: Path, root: Path, config: Any
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
