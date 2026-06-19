"""CLI-level integration tests — orchestration of ConfigManager + HookRegistrar."""

import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_wiki.cli import main


class TestInitCommand:
    """Tests for kb init CLI command."""

    def test_init_creates_marker_and_local_settings(self):
        """kb init defaults to repo-local .claude/settings.local.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()

            exit_code = main(["init", "--path", str(repo)])
            assert exit_code == 0

            marker = repo / ".claude-wiki.lock"
            assert marker.exists()
            local_settings = repo / ".claude" / "settings.local.json"
            assert local_settings.exists()

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

            assert (repo / ".claude-wiki.lock").exists()

    def test_init_global_flag_writes_user_settings(self):
        """kb init --global writes hooks to ~/.claude/settings.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                exit_code = main(["init", "--path", str(repo), "--global"])
                assert exit_code == 0

            global_settings = claude_dir / "settings.json"
            assert global_settings.exists()
            assert not (repo / ".claude" / "settings.local.json").exists()

    def test_init_force_flag_overwrites(self):
        """kb init --force overwrites existing marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text('{"repo_name": "old-name"}')
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                exit_code = main(["init", "--path", str(repo), "--force"])
                assert exit_code == 0

            data = __import__("json").loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_name"] == "my-project"
