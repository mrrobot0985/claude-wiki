"""Tests for `kb compile`.

All LLM calls are mocked so these tests run offline and deterministically.
"""

import json
import types
from pathlib import Path
from typing import Any

import pytest

from claude_wiki.cli import main
from claude_wiki.commands import compile as _compile_module  # noqa: F401
from claude_wiki.commands.compile import (
    _DEFAULT_SCHEMA,
    _compile_one,
    _extract_sources,
    _list_existing_articles,
    _read_index,
    _read_schema,
)
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

    def test_extract_sources_no_frontmatter(self) -> None:
        """Content without YAML frontmatter returns an empty source list."""
        assert _extract_sources("plain markdown with no frontmatter") == []

    def test_extract_sources_missing_closing(self) -> None:
        """A frontmatter opener without a closer returns an empty source list."""
        assert _extract_sources("---\ntitle: no closing") == []

    def test_extract_sources_inline_list(self) -> None:
        """Inline YAML list syntax is parsed into individual source entries."""
        content = '---\nsources: ["daily/2026-06-19.md", "daily/2026-06-18.md"]\n---\n'
        assert _extract_sources(content) == [
            "daily/2026-06-19.md",
            "daily/2026-06-18.md",
        ]

    def test_extract_sources_inline_single(self) -> None:
        """A single inline source value is captured."""
        content = '---\nsources: "daily/2026-06-19.md"\n---\n'
        assert _extract_sources(content) == ["daily/2026-06-19.md"]

    def test_extract_sources_stops_at_colon(self) -> None:
        """Source parsing stops when a new key is encountered."""
        content = '---\nsources:\n  - "daily/2026-06-19.md"\ntitle: next key\n---\n'
        assert _extract_sources(content) == ["daily/2026-06-19.md"]

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
        """`_compile_one` drives the async LLM helper with a fake SDK."""

        class TextBlock:
            pass

        class AssistantMessage:
            content = [TextBlock()]

        class ResultMessage:
            total_cost_usd = 0.42

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: Any) -> None:
                pass

        async def query(**kwargs: Any) -> Any:
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

    def test_schema_cites_daily_logs_as_plain_text(self) -> None:
        """Daily-log citations are plain text, never [[wikilinks]] (ADR-007)."""
        assert "[[daily/" not in _DEFAULT_SCHEMA
        assert "daily/YYYY-MM-DD.md" in _DEFAULT_SCHEMA

    def test_compile_prompt_cites_daily_as_plain_text(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        """The prompt sent to the compiler contains no [[daily/…]] wikilinks."""

        class TextBlock:
            pass

        class AssistantMessage:
            content = [TextBlock()]

        class ResultMessage:
            total_cost_usd = 0.0

        class ClaudeAgentOptions:
            def __init__(self, **kwargs: Any) -> None:
                pass

        captured: dict[str, Any] = {}

        async def query(**kwargs: Any) -> Any:
            captured["prompt"] = kwargs.get("prompt", "")
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
        # (The prohibition text may mention [[daily/…]] with an ellipsis — that's fine.)
        assert "[[daily/YYYY-MM-DD.md]]" not in prompt
        assert "daily/2026-06-19.md" in prompt
        assert "- daily/YYYY-MM-DD.md" in prompt

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
