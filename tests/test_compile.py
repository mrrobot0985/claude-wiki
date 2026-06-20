"""Tests for `kb compile`.

All LLM calls are mocked so these tests run offline and deterministically.
"""

import json
import types
from pathlib import Path
from typing import Any

from claude_wiki.cli import main
from claude_wiki.commands import compile as _compile_module  # noqa: F401
from claude_wiki.commands.compile import (
    _collect_backlinks,
    _compile_one,
    _ensure_daily_symlink,
    _extract_sources,
    _list_existing_articles,
    _read_index,
    _read_schema,
)
from claude_wiki.models import ProjectConfig


def _make_repo(tmpdir: str) -> tuple[Path, Path]:
    """Create a fake repo with .git, marker, and absolute KB directory."""
    repo = Path(tmpdir) / "my-project"
    repo.mkdir()
    (repo / ".git").mkdir()

    kb_root = Path(tmpdir) / "kb"
    marker = repo / ".claude-wiki.lock"
    marker.write_text(
        json.dumps(
            {
                "repo_name": "my-project",
                "repo_owner": "owner",
                "kb_dir": str(kb_root),
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
        state_path = kb_root / "state.json"
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

        state_path = kb_root / "state.json"
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

        state = json.loads((kb_root / "state.json").read_text())
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
        assert not (kb_root / "state.json").exists()

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
            index = root / "index.md"
            if not index.exists():
                index.write_text(
                    "# Knowledge Base Index\n\n"
                    "| Article | Summary | Compiled From | Updated |\n"
                    "|---------|---------|---------------|---------|"
                )
            content = index.read_text()
            content += "\n| [[concepts/asyncio-patterns]] | asyncio tips | daily/2026-06-19.md | 2026-06-19 |"
            index.write_text(content)
            return 0.0

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=fake_compile
        )

        exit_code = main(["compile"])

        assert exit_code == 0
        index_path = kb_root / "index.md"
        assert index_path.exists()
        assert "[[concepts/asyncio-patterns]]" in index_path.read_text()

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


class TestDailySymlink:
    """Tests for issue #7: daily log wikilinks when KB is outside the repo."""

    def _make_user_repo(
        self, tmp_path: Path, monkeypatch: Any
    ) -> tuple[Path, Path, Path]:
        """Create a repo configured with kb_dir='user' and return repo, kb_root, daily_dir."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        xdg_data = tmp_path / "xdg-data"
        xdg_data.mkdir()
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg_data))

        kb_root = xdg_data / "claude-wiki" / "local" / "my-project"
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "my-project",
                    "repo_owner": "local",
                    "kb_dir": "user",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        return repo, kb_root, daily_dir

    def test_user_mode_creates_absolute_daily_symlink(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """With kb_dir='user', an absolute daily/ symlink is created in KB root."""
        repo, kb_root, daily_dir = self._make_user_repo(tmp_path, monkeypatch)
        (daily_dir / "2026-06-19.md").write_text("log content")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile"])

        assert exit_code == 0
        symlink = kb_root / "daily"
        assert symlink.is_symlink()
        assert symlink.resolve() == daily_dir.resolve()
        assert not str(symlink.readlink()).startswith("..")

    def test_project_mode_creates_relative_daily_symlink(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """With kb_dir='project', a relative daily/ symlink keeps KB relocatable."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = repo / ".claude" / "knowledge"
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "my-project",
                    "repo_owner": "local",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("log content")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile"])

        assert exit_code == 0
        symlink = kb_root / "daily"
        assert symlink.is_symlink()
        # Relative link should walk up from .claude/knowledge/daily to repo/daily.
        assert str(symlink.readlink()) == "../../daily"
        assert symlink.resolve() == daily_dir.resolve()

    def test_absolute_kb_dir_creates_daily_symlink(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """With an absolute kb_dir path, an absolute daily symlink is created."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = tmp_path / "custom-kb"
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "my-project",
                    "repo_owner": "local",
                    "kb_dir": str(kb_root),
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        (daily_dir / "2026-06-19.md").write_text("log content")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile"])

        assert exit_code == 0
        symlink = kb_root / "daily"
        assert symlink.is_symlink()
        assert symlink.resolve() == daily_dir.resolve()

    def test_missing_daily_dir_skips_symlink(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """If the repo daily directory does not exist, compile skips symlink creation."""
        repo, kb_root, _daily_dir = self._make_user_repo(tmp_path, monkeypatch)

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile"])

        assert exit_code == 0
        assert not (kb_root / "daily").exists()

    def test_existing_daily_path_warns_and_skips(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any, capsys: Any
    ) -> None:
        """If kb_root/daily already exists as a file/dir, the command warns and skips."""
        repo, kb_root, daily_dir = self._make_user_repo(tmp_path, monkeypatch)
        (daily_dir / "2026-06-19.md").write_text("log content")
        kb_root.mkdir(parents=True, exist_ok=True)
        existing = kb_root / "daily"
        existing.write_text("I am not a symlink")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        exit_code = main(["compile"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert existing.is_file()
        assert "not overwriting" in captured.err

    def test_dry_run_does_not_create_symlink(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--dry-run`` does not create the daily/ symlink."""
        repo, kb_root, daily_dir = self._make_user_repo(tmp_path, monkeypatch)
        (daily_dir / "2026-06-19.md").write_text("log content")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one")

        exit_code = main(["compile", "--dry-run"])

        assert exit_code == 0
        assert not (kb_root / "daily").exists()

    def test_symlink_creation_is_idempotent(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """Re-running compile leaves an existing correct symlink intact."""
        repo, kb_root, daily_dir = self._make_user_repo(tmp_path, monkeypatch)
        (daily_dir / "2026-06-19.md").write_text("log content")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one", return_value=0.0)

        main(["compile"])
        first_link = kb_root / "daily"
        assert first_link.is_symlink()
        first_target = first_link.readlink()

        main(["compile"])
        second_link = kb_root / "daily"

        assert second_link.readlink() == first_target


class TestDailyBacklinks:
    """Tests for issue #10: bidirectional provenance via daily log backlinks."""

    def _make_repo(self, tmp_path: Path) -> tuple[Path, Path, Path]:
        """Create a project-mode repo and return repo, kb_root, daily_dir."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = repo / ".claude" / "knowledge"
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "my-project",
                    "repo_owner": "local",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        daily_dir = repo / "daily"
        daily_dir.mkdir()
        return repo, kb_root, daily_dir

    def _fake_compile_with_articles(self, repo_root: Path, kb_root: Path) -> Any:
        """Return a fake compile function that writes concepts/connections articles."""

        def fake(log_path: Path, _repo_root: Path, root: Path, _config: Any) -> float:
            concept_dir = root / "concepts"
            concept_dir.mkdir(parents=True, exist_ok=True)
            (concept_dir / "asyncio-patterns.md").write_text(
                '---\ntitle: asyncio patterns\nsources:\n  - "daily/2026-06-19.md"\n---\n'
            )
            connection_dir = root / "connections"
            connection_dir.mkdir(parents=True, exist_ok=True)
            (connection_dir / "asyncio-concurrency.md").write_text(
                '---\ntitle: asyncio concurrency\nsources:\n  - "daily/2026-06-19.md"\n---\n'
            )
            qa_dir = root / "qa"
            qa_dir.mkdir(parents=True, exist_ok=True)
            (qa_dir / "why-asyncio.md").write_text(
                '---\ntitle: why asyncio\nsources:\n  - "daily/2026-06-19.md"\n---\n'
            )
            return 0.0

        return fake

    def test_appends_compiled_knowledge_section(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """A successful compile adds a backlink section to the daily log."""
        repo, _kb_root, daily_dir = self._make_repo(tmp_path)
        log = daily_dir / "2026-06-19.md"
        log.write_text("discussed asyncio patterns")

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=self._fake_compile_with_articles(
                repo, repo / ".claude" / "knowledge"
            ),
        )

        exit_code = main(["compile"])

        assert exit_code == 0
        content = log.read_text()
        assert "## Compiled Knowledge" in content
        assert "[[concepts/asyncio-patterns]]" in content
        assert "[[connections/asyncio-concurrency]]" in content
        assert "[[qa/why-asyncio]]" in content

    def test_recompile_replaces_existing_backlinks_section(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """Re-compiling the same log replaces the old backlink section."""
        repo, _kb_root, daily_dir = self._make_repo(tmp_path)
        log = daily_dir / "2026-06-19.md"
        log.write_text(
            "original log content\n\n## Compiled Knowledge\n\n- [[concepts/stale]]\n"
        )

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=self._fake_compile_with_articles(
                repo, repo / ".claude" / "knowledge"
            ),
        )

        main(["compile"])
        content = log.read_text()

        assert content.count("## Compiled Knowledge") == 1
        assert "[[concepts/stale]]" not in content
        assert "[[concepts/asyncio-patterns]]" in content

    def test_no_articles_writes_empty_backlinks_section(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """If compilation produces no articles, the section is written empty."""
        repo, _kb_root, daily_dir = self._make_repo(tmp_path)
        log = daily_dir / "2026-06-19.md"
        log.write_text("random chat with no concepts")

        def fake_no_articles(
            _log_path: Path, _repo_root: Path, _root: Path, _config: Any
        ) -> float:
            return 0.0

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=fake_no_articles
        )

        exit_code = main(["compile"])

        assert exit_code == 0
        content = log.read_text()
        assert "## Compiled Knowledge" in content
        assert "No articles compiled" in content

    def test_dry_run_does_not_update_backlinks(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--dry-run`` does not touch the daily log backlink section."""
        repo, _kb_root, daily_dir = self._make_repo(tmp_path)
        log = daily_dir / "2026-06-19.md"
        log.write_text("discussed asyncio patterns")

        monkeypatch.chdir(repo)
        mocker.patch("claude_wiki.commands.compile._compile_one")

        exit_code = main(["compile", "--dry-run"])

        assert exit_code == 0
        assert "## Compiled Knowledge" not in log.read_text()

    def test_failed_compile_does_not_update_backlinks(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """If compilation raises, the daily log keeps its original content."""
        repo, _kb_root, daily_dir = self._make_repo(tmp_path)
        log = daily_dir / "2026-06-19.md"
        log.write_text("original content")

        def fake_error(
            _log_path: Path, _repo_root: Path, _root: Path, _config: Any
        ) -> float:
            raise RuntimeError("compiler exploded")

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one", side_effect=fake_error
        )

        exit_code = main(["compile"])

        assert exit_code == 0
        assert log.read_text() == "original content"

    def test_only_compiled_logs_get_backlinks(
        self, monkeypatch: Any, tmp_path: Path, mocker: Any
    ) -> None:
        """``--file`` only updates the target log's backlink section."""
        repo, _kb_root, daily_dir = self._make_repo(tmp_path)
        first = daily_dir / "2026-06-18.md"
        first.write_text("old discussion")
        second = daily_dir / "2026-06-19.md"
        second.write_text("discussed asyncio patterns")

        monkeypatch.chdir(repo)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=self._fake_compile_with_articles(
                repo, repo / ".claude" / "knowledge"
            ),
        )

        exit_code = main(["compile", "--file", "daily/2026-06-19.md"])

        assert exit_code == 0
        assert "## Compiled Knowledge" in second.read_text()
        assert "## Compiled Knowledge" not in first.read_text()


class TestCompileGaps:
    """Cover edge cases and small helpers not exercised by the main flows."""

    def test_ensure_daily_symlink_dry_run(self, tmp_path: Path) -> None:
        """``dry_run`` skips creating the daily/ symlink."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb = tmp_path / "kb"
        (repo / "daily").mkdir()
        config = ProjectConfig(repo_name="dry-run", kb_dir=kb)

        _ensure_daily_symlink(repo, kb, config, dry_run=True)

        assert not (kb / "daily").exists()

    def test_ensure_daily_symlink_missing_source(self, tmp_path: Path) -> None:
        """If the repo daily directory is missing, symlink creation is skipped."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb = tmp_path / "kb"
        config = ProjectConfig(repo_name="no-daily", kb_dir=kb)

        _ensure_daily_symlink(repo, kb, config, dry_run=False)

        assert not (kb / "daily").exists()

    def test_ensure_daily_symlink_idempotent(self, tmp_path: Path) -> None:
        """An existing correct symlink is left untouched."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb = tmp_path / "kb"
        kb.mkdir()
        daily = repo / "daily"
        daily.mkdir()
        link = kb / "daily"
        link.symlink_to(daily.resolve(), target_is_directory=True)
        config = ProjectConfig(repo_name="idempotent", kb_dir=kb)

        _ensure_daily_symlink(repo, kb, config, dry_run=False)

        assert link.is_symlink()
        assert link.resolve() == daily.resolve()

    def test_ensure_daily_symlink_existing_wrong_target_warns(
        self, tmp_path: Path, capsys: Any
    ) -> None:
        """A symlink pointing elsewhere triggers a warning and is preserved."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb = tmp_path / "kb"
        kb.mkdir()
        daily = repo / "daily"
        daily.mkdir()
        other = tmp_path / "other"
        other.mkdir()
        link = kb / "daily"
        link.symlink_to(other.resolve(), target_is_directory=True)
        config = ProjectConfig(repo_name="wrong-link", kb_dir=kb)

        _ensure_daily_symlink(repo, kb, config, dry_run=False)
        captured = capsys.readouterr()

        assert "not overwriting" in captured.err
        assert link.resolve() == other.resolve()

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

    def test_collect_backlinks_skips_missing_subdir(self, tmp_path: Path) -> None:
        """If no KB subdirectories exist, no backlinks are found."""
        kb = tmp_path / "kb"
        kb.mkdir()
        assert _collect_backlinks(kb, "daily/2026-06-19.md") == []

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

    def test_read_index_exists(self, tmp_path: Path) -> None:
        """An existing index.md is returned verbatim."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "index.md").write_text("# Custom Index\n")

        assert _read_index(kb) == "# Custom Index\n"

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
