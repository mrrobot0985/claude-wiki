"""CLI-level integration tests — orchestration of ConfigManager + HookRegistrar."""

import json
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

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_name"] == "my-project"


class TestMigrateCommand:
    """Tests for claude-wiki migrate with path override flags."""

    def _bootstrap_repo(self, repo: Path) -> None:
        """Create lock, knowledge, and daily directories."""
        config = {
            "repo_name": repo.name,
            "repo_owner": "local",
            "kb_dir": "knowledge",
            "daily_dir": "daily",
            "reports_dir": "reports",
            "timezone": "UTC",
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(config))
        (repo / "knowledge").mkdir()
        (repo / "knowledge" / "index.md").write_text("# Index")
        (repo / "daily").mkdir()
        (repo / "daily" / "2024-01-01.md").write_text("log")

    def test_migrate_kb_dir_flag(self):
        """--kb-dir overrides the knowledge base path and moves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._bootstrap_repo(repo)

            with patch("claude_wiki.cli.GlobalIndexManager"):
                exit_code = main(["migrate", "--path", str(repo), "--kb-dir", "wiki"])

            assert exit_code == 0
            assert not (repo / "knowledge").exists()
            assert (repo / "wiki" / "index.md").exists()
            lock = json.loads((repo / ".claude-wiki.lock").read_text())
            assert lock["kb_dir"] == "wiki"

    def test_migrate_daily_dir_flag(self):
        """--daily-dir overrides the daily log path and moves data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._bootstrap_repo(repo)

            with patch("claude_wiki.cli.GlobalIndexManager"):
                exit_code = main(
                    ["migrate", "--path", str(repo), "--daily-dir", "logs"]
                )

            assert exit_code == 0
            assert not (repo / "daily").exists()
            assert (repo / "logs" / "2024-01-01.md").exists()
            lock = json.loads((repo / ".claude-wiki.lock").read_text())
            assert lock["daily_dir"] == "logs"

    def test_migrate_reports_dir_flag(self):
        """--reports-dir overrides the reports path and persists to config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._bootstrap_repo(repo)

            with patch("claude_wiki.cli.GlobalIndexManager"):
                exit_code = main(
                    ["migrate", "--path", str(repo), "--reports-dir", "custom-reports"]
                )

            assert exit_code == 0
            lock = json.loads((repo / ".claude-wiki.lock").read_text())
            assert lock["reports_dir"] == "custom-reports"
