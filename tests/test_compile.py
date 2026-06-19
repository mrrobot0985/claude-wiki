"""Tests for `kb compile`.

All LLM calls are mocked so these tests run offline and deterministically.
"""

import json
from pathlib import Path
from typing import Any

from claude_wiki.cli import main
from claude_wiki.commands import compile as _compile_module  # noqa: F401


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
