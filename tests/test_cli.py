"""CLI-level integration tests — orchestration of ConfigManager + HookRegistrar."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_kb.cli import main


class TestInitCommand:
    """Tests for kb init CLI command."""

    def test_init_creates_marker_and_settings(self):
        """kb init creates .claude-wiki.json and updates ~/.claude/settings.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                exit_code = main(["init", "--path", str(repo)])
                assert exit_code == 0

            marker = repo / ".claude-wiki.json"
            assert marker.exists()
            assert (claude_dir / "settings.json").exists()

    def test_init_from_subdirectory(self):
        """kb init works from any subdirectory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            subdir = repo / "src" / "deep"
            subdir.mkdir(parents=True)
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                exit_code = main(["init", "--path", str(subdir)])
                assert exit_code == 0

            assert (repo / ".claude-wiki.json").exists()

    def test_init_force_flag_overwrites(self):
        """kb init --force overwrites existing marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.json").write_text('{"repo_name": "old-name"}')
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                exit_code = main(["init", "--path", str(repo), "--force"])
                assert exit_code == 0

            data = __import__("json").loads((repo / ".claude-wiki.json").read_text())
            assert data["repo_name"] == "my-project"
