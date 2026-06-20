"""CLI-level integration tests — orchestration of ConfigManager + HookRegistrar."""

import importlib
import json
import pkgutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_wiki.cli import _print_migration_result, _register_commands, main
from claude_wiki.config import ConfigManager
from claude_wiki.models import MigrationResult, ProjectConfig


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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "old-name",
                        "repo_owner": "local",
                        "kb_dir": "project",
                        "daily_dir": "daily",
                        "reports_dir": "reports",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                exit_code = main(["init", "--path", str(repo), "--force"])
                assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_name"] == "my-project"

    def test_init_infers_owner_from_git_remote(self):
        """Fresh init infers repo_owner from origin remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "claude-wiki"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/mrrobot0985/claude-wiki.git",
                ],
                check=True,
                capture_output=True,
            )
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo)])
                    assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_owner"] == "mrrobot0985"

    def test_init_fallback_local_without_remote(self):
        """Fresh init falls back to repo_owner=local when no origin remote exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "orphan-project"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo)])
                    assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_owner"] == "local"

    def test_init_force_reinfers_owner(self):
        """kb init --force re-infers repo_owner from current remote."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "renamed-project"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    "git@github.com:old-owner/old-repo.git",
                ],
                check=True,
                capture_output=True,
            )
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "renamed-project",
                        "repo_owner": "old-owner",
                        "kb_dir": "project",
                        "daily_dir": "daily",
                        "reports_dir": "reports",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            # Change the remote to a new owner.
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "set-url",
                    "origin",
                    "https://github.com/new-owner/renamed-project.git",
                ],
                check=True,
                capture_output=True,
            )

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo), "--force"])
                    assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_owner"] == "new-owner"

    def test_init_reinfers_owner_without_force(self, capsys):
        """Running init without --force updates a stale repo_owner from remotes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "claude-wiki"
            repo.mkdir()
            subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repo),
                    "remote",
                    "add",
                    "origin",
                    "https://github.com/mrrobot0985/claude-wiki.git",
                ],
                check=True,
                capture_output=True,
            )
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "claude-wiki",
                        "repo_owner": "local",
                        "kb_dir": "project",
                        "daily_dir": "daily",
                        "reports_dir": "reports",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo)])

            captured = capsys.readouterr()
            assert exit_code == 0
            assert "already initialised" not in captured.err
            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_owner"] == "mrrobot0985"

    def test_init_interactive_uses_defaults(self):
        """TTY init with empty answers writes default config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            inputs = ["", "", "", "", "", "", ""]

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input", side_effect=inputs):
                            exit_code = main(["init", "--path", str(repo)])
                            assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_owner"] == "local"
            assert data["kb_dir"] == "project"
            assert data["daily_dir"] == ".claude/daily"
            assert data["reports_dir"] == "reports"
            assert data["timezone"] == "UTC"
            assert data["compile_after_hour"] == 18
            assert (repo / ".claude" / "settings.local.json").exists()

    def test_init_interactive_custom_values(self):
        """TTY init captures custom interactive values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            inputs = [
                "custom-owner",
                "custom",
                "/tmp/custom-kb",
                "logs",
                "findings",
                "America/New_York",
                "9",
                "global",
            ]

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input", side_effect=inputs):
                            exit_code = main(["init", "--path", str(repo)])
                            assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_owner"] == "custom-owner"
            assert data["kb_dir"] == "/tmp/custom-kb"
            assert data["daily_dir"] == "logs"
            assert data["reports_dir"] == "findings"
            assert data["timezone"] == "America/New_York"
            assert data["compile_after_hour"] == 9
            assert (claude_dir / "settings.json").exists()
            assert not (repo / ".claude" / "settings.local.json").exists()

    def test_init_interactive_ctrl_c_aborts(self):
        """Ctrl-C during interactive prompts aborts without writing files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()

            def _raise(*_args, **_kwargs):
                raise KeyboardInterrupt()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input", side_effect=_raise):
                            exit_code = main(["init", "--path", str(repo)])
                            assert exit_code == 1

            assert not (repo / ".claude-wiki.lock").exists()

    def test_init_non_tty_is_silent(self):
        """Non-TTY init behaves silently with defaults."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=False):
                        with patch("builtins.input") as mock_input:
                            exit_code = main(["init", "--path", str(repo)])
                            assert exit_code == 0
                            mock_input.assert_not_called()

            assert (repo / ".claude-wiki.lock").exists()

    def test_init_global_flag_disables_interactivity(self):
        """--global prevents prompts even when stdin is a TTY."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input") as mock_input:
                            exit_code = main(["init", "--path", str(repo), "--global"])
                            assert exit_code == 0
                            mock_input.assert_not_called()

            assert (claude_dir / "settings.json").exists()
            assert not (repo / ".claude" / "settings.local.json").exists()

    def test_init_interactive_invalid_input_reprompts(self):
        """Out-of-range compile hour is rejected and re-prompted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            inputs = ["", "", "", "", "", "abc", "25", "9", ""]

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input", side_effect=inputs):
                            exit_code = main(["init", "--path", str(repo)])
                            assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["compile_after_hour"] == 9

    def test_init_interactive_force_confirm_overwrites(self):
        """Interactive --force asks for confirmation before overwriting."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "old-name",
                        "repo_owner": "old-owner",
                        "kb_dir": "project",
                        "daily_dir": "daily",
                        "reports_dir": "reports",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            inputs = ["y", "", "", "", "", "", "", ""]

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input", side_effect=inputs):
                            exit_code = main(["init", "--path", str(repo), "--force"])
                            assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_name"] == "my-project"
            assert data["repo_owner"] == "local"

    def test_init_interactive_force_decline_aborts(self):
        """Interactive --force with declined confirmation aborts."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "old-name",
                        "repo_owner": "old-owner",
                        "kb_dir": "project",
                        "daily_dir": "daily",
                        "reports_dir": "reports",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input", side_effect=["n"]):
                            exit_code = main(["init", "--path", str(repo), "--force"])
                            assert exit_code == 1

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["repo_name"] == "old-name"
            assert data["repo_owner"] == "old-owner"


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
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(config))
        (repo / "knowledge").mkdir()
        (repo / "knowledge" / f"{repo.name}.md").write_text("# Index")
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
            assert (repo / "wiki" / "my-project.md").exists()
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

    def test_migrate_reports_dir_flag_emits_deprecation_warning(self, capsys):
        """--reports-dir is deprecated and does not affect config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._bootstrap_repo(repo)

            with patch("claude_wiki.cli.GlobalIndexManager"):
                exit_code = main(
                    ["migrate", "--path", str(repo), "--reports-dir", "custom-reports"]
                )

            captured = capsys.readouterr()
            assert exit_code == 0
            assert "--reports-dir is deprecated and ignored" in captured.err
            lock = json.loads((repo / ".claude-wiki.lock").read_text())
            assert lock["reports_dir"] == "reports"


class TestCliEdgeCases:
    """Tests covering uncovered paths in cli.py."""

    def test_main_no_command_prints_help(self, capsys):
        """Calling main with no arguments prints help and exits 1."""
        exit_code = main([])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "usage:" in captured.out

    def test_main_unimplemented_command(self, monkeypatch, capsys):
        """A subparser without a matching handler prints not implemented."""

        def fake_register(subparsers, handlers):
            subparsers.add_parser("unimplemented", help="test command")
            # Intentionally not adding to handlers

        monkeypatch.setattr("claude_wiki.cli._register_commands", fake_register)
        exit_code = main(["unimplemented"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "not yet implemented" in captured.err

    def test_register_commands_skips_broken_modules(self, monkeypatch):
        """Broken command modules are skipped during discovery without crashing."""
        fake_subparsers = type("Subparsers", (), {"add_parser": lambda *a, **k: None})()
        handlers: dict[str, Any] = {}

        def fake_iter_modules(*_args, **_kwargs):
            yield (None, "claude_wiki.commands.broken", False)

        def fake_import_module(_name):
            raise ImportError("boom")

        monkeypatch.setattr(pkgutil, "iter_modules", fake_iter_modules)
        monkeypatch.setattr(importlib, "import_module", fake_import_module)

        _register_commands(fake_subparsers, handlers)
        assert handlers == {}

    def test_init_not_git_repo(self, capsys, tmp_path):
        """init outside a git repo prints an error and exits 1."""
        exit_code = main(["init", "--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Not in a git repository" in captured.err

    def test_init_marker_exists_without_force(self, capsys, tmp_path, monkeypatch):
        """init on an already-initialised repo without --force exits 0."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude-wiki.lock").write_text(
            json.dumps(
                {
                    "repo_name": "old-name",
                    "repo_owner": "old-owner",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "reports_dir": "reports",
                    "timezone": "UTC",
                    "compile_after_hour": 18,
                }
            )
        )

        with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=False):
            with patch("claude_wiki.cli.GlobalIndexManager"):
                exit_code = main(["init", "--path", str(repo)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "already initialised" in captured.err
        data = json.loads((repo / ".claude-wiki.lock").read_text())
        assert data["repo_name"] == "old-name"

    def test_init_migration_performed_prints_result(
        self, mocker, monkeypatch, tmp_path, capsys
    ):
        """When init migrator reports a migration, the result is printed."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (tmp_path / ".claude").mkdir()
        defaults = ProjectConfig(repo_name=repo.name)

        fake_detector = ConfigManager()
        fake_detector.find_repo_root = mocker.MagicMock(return_value=repo)
        fake_detector.get_kb_root = mocker.MagicMock(
            return_value=repo / ".claude" / "knowledge"
        )
        fake_loader = mocker.MagicMock()
        fake_loader.load.return_value = defaults
        fake_migrator = mocker.MagicMock()
        fake_migrator.check_and_migrate.return_value = MigrationResult(
            migrated=True,
            old_kb_dir=Path("old_kb"),
            new_kb_dir=Path("new_kb"),
        )
        fake_owner = mocker.MagicMock()
        fake_owner.infer_repo_owner.return_value = "local"

        mocker.patch(
            "claude_wiki.cli.DefaultConfigResolver.build",
            return_value=(
                fake_detector,
                fake_loader,
                mocker.MagicMock(),
                fake_migrator,
                fake_owner,
            ),
        )
        mocker.patch("claude_wiki.cli.GlobalIndexManager")
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=False):
            exit_code = main(["init", "--path", str(repo)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Migration performed:" in captured.out
        assert "kb_dir: old_kb -> new_kb" in captured.out

    def test_init_migration_errors_printed(self, mocker, monkeypatch, tmp_path, capsys):
        """When init migrator reports errors, they are printed to stderr."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (tmp_path / ".claude").mkdir()
        defaults = ProjectConfig(repo_name=repo.name)

        fake_detector = ConfigManager()
        fake_detector.find_repo_root = mocker.MagicMock(return_value=repo)
        fake_detector.get_kb_root = mocker.MagicMock(
            return_value=repo / ".claude" / "knowledge"
        )
        fake_loader = mocker.MagicMock()
        fake_loader.load.return_value = defaults
        fake_migrator = mocker.MagicMock()
        fake_migrator.check_and_migrate.return_value = MigrationResult(
            migrated=False, errors=["migration failed"]
        )
        fake_owner = mocker.MagicMock()
        fake_owner.infer_repo_owner.return_value = "local"

        mocker.patch(
            "claude_wiki.cli.DefaultConfigResolver.build",
            return_value=(
                fake_detector,
                fake_loader,
                mocker.MagicMock(),
                fake_migrator,
                fake_owner,
            ),
        )
        mocker.patch("claude_wiki.cli.GlobalIndexManager")
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        with patch.dict("os.environ", {"HOME": str(tmp_path)}, clear=False):
            exit_code = main(["init", "--path", str(repo)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Error: migration failed" in captured.err

    def test_migrate_not_git_repo(self, capsys, tmp_path):
        """migrate outside a git repo prints an error and exits 1."""
        exit_code = main(["migrate", "--path", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Not in a git repository" in captured.err

    def test_migrate_no_lock_file(self, capsys, tmp_path):
        """migrate in a git repo without a lock file prints an error and exits 1."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()

        exit_code = main(["migrate", "--path", str(repo)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Run 'claude-wiki init' first" in captured.err

    def test_migrate_no_changes(self, capsys, tmp_path):
        """migrate with no path overrides reports no migration needed."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude-wiki.lock").write_text(
            json.dumps(
                {
                    "repo_name": repo.name,
                    "repo_owner": "local",
                    "kb_dir": "knowledge",
                    "daily_dir": "daily",
                    "reports_dir": "reports",
                    "timezone": "UTC",
                    "compile_after_hour": 18,
                }
            )
        )

        exit_code = main(["migrate", "--path", str(repo)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No migration needed" in captured.out

    def test_migrate_errors_return_one(self, mocker, tmp_path, capsys):
        """When migrate reports errors, cli exits with status 1."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude-wiki.lock").write_text(
            json.dumps(
                {
                    "repo_name": repo.name,
                    "repo_owner": "local",
                    "kb_dir": "knowledge",
                    "daily_dir": "daily",
                    "reports_dir": "reports",
                    "timezone": "UTC",
                    "compile_after_hour": 18,
                }
            )
        )
        previous = ProjectConfig.from_dict(
            {
                "repo_name": repo.name,
                "repo_owner": "local",
                "kb_dir": "knowledge",
                "daily_dir": "daily",
                "reports_dir": "reports",
                "timezone": "UTC",
                "compile_after_hour": 18,
            }
        )

        fake_detector = mocker.MagicMock()
        fake_detector.find_repo_root.return_value = repo
        fake_loader = mocker.MagicMock()
        fake_loader.load.return_value = previous
        fake_migrator = mocker.MagicMock()
        fake_migrator.check_and_migrate.return_value = MigrationResult(
            migrated=True,
            old_kb_dir=Path("knowledge"),
            new_kb_dir=Path("wiki"),
            errors=["move failed"],
        )

        mocker.patch(
            "claude_wiki.cli.DefaultConfigResolver.build",
            return_value=(
                fake_detector,
                fake_loader,
                mocker.MagicMock(),
                fake_migrator,
                mocker.MagicMock(),
            ),
        )
        mocker.patch("claude_wiki.cli.GlobalIndexManager")

        exit_code = main(["migrate", "--path", str(repo), "--kb-dir", "wiki"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "Error: move failed" in captured.out

    def test_print_migration_result_warnings_and_errors(self, capsys):
        """_print_migration_result emits warnings and errors."""
        result = MigrationResult(
            migrated=False,
            errors=["err1"],
            warnings=["warn1"],
        )
        _print_migration_result(result)
        captured = capsys.readouterr()
        assert "Warning: warn1" in captured.out
        assert "Error: err1" in captured.out

    def test_main_module_invocation(self, monkeypatch):
        """Running cli.py as __main__ with no args exits 1."""
        import runpy

        monkeypatch.setattr(sys, "argv", ["claude-wiki.cli"])
        with pytest.raises(SystemExit) as exc_info:
            runpy.run_module("claude_wiki.cli", run_name="__main__")
        assert exc_info.value.code == 1
