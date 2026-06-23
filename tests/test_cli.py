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
from claude_wiki.factories import CLAUDE_WIKI_HOOK_COMMAND
from claude_wiki.models import MigrationResult, ProjectConfig
from platformdirs import user_data_dir


class TestInitCommand:
    """Tests for kb init CLI command."""

    def _install_global_hooks(self, home_dir: Path) -> None:
        """Write a fake ~/.claude/settings.json with claude-wiki hook commands."""
        claude_dir = home_dir / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        (claude_dir / "settings.json").write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{CLAUDE_WIKI_HOOK_COMMAND} SessionStart",
                                        "timeout": 15,
                                    }
                                ],
                            }
                        ],
                        "SessionEnd": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{CLAUDE_WIKI_HOOK_COMMAND} SessionEnd",
                                        "timeout": 10,
                                    }
                                ],
                            }
                        ],
                        "PreCompact": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{CLAUDE_WIKI_HOOK_COMMAND} PreCompact",
                                        "timeout": 10,
                                    }
                                ],
                            }
                        ],
                    }
                }
            )
        )

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
                        "layout_version": "2",
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
                        "layout_version": "2",
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
                        "layout_version": "2",
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

    def test_init_no_hooks_skips_install_and_settings_files(self, capsys):
        """--no-hooks writes lock and registers without touching any settings file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager") as mock_global:
                    exit_code = main(["init", "--path", str(repo), "--no-hooks"])
                    assert exit_code == 0
                    mock_global.return_value.register.assert_called_once()

            assert (repo / ".claude-wiki.lock").exists()
            assert not (repo / ".claude" / "settings.local.json").exists()
            assert not (claude_dir / "settings.json").exists()
            captured = capsys.readouterr()
            assert "hooks skipped" in captured.out.lower()

    def test_init_global_and_no_hooks_skips_all_settings(self, capsys):
        """--global --no-hooks registers but never writes a settings file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager") as mock_global:
                    exit_code = main(
                        ["init", "--path", str(repo), "--global", "--no-hooks"]
                    )
                    assert exit_code == 0
                    mock_global.return_value.register.assert_called_once()

            assert (repo / ".claude-wiki.lock").exists()
            assert not (claude_dir / "settings.json").exists()
            assert not (repo / ".claude" / "settings.local.json").exists()
            captured = capsys.readouterr()
            assert "hooks skipped" in captured.out.lower()

    def test_init_no_hooks_disables_interactivity(self):
        """--no-hooks prevents prompts even when stdin is a TTY."""
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
                            exit_code = main(
                                ["init", "--path", str(repo), "--no-hooks"]
                            )
                            assert exit_code == 0
                            mock_input.assert_not_called()

            assert (repo / ".claude-wiki.lock").exists()
            assert not (repo / ".claude" / "settings.local.json").exists()
            assert not (claude_dir / "settings.json").exists()

    def test_init_aborts_when_global_hooks_exist(self, capsys):
        """kb init aborts before writing repo-local settings if global hooks exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._install_global_hooks(Path(tmpdir))

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo)])

            captured = capsys.readouterr()
            assert exit_code == 1
            assert not (repo / ".claude" / "settings.local.json").exists()
            assert "--no-hooks" in captured.err
            assert "--global" in captured.err

    def test_init_no_hooks_succeeds_when_global_hooks_exist(self, capsys):
        """kb init --no-hooks succeeds and skips all settings files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._install_global_hooks(Path(tmpdir))

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager") as mock_global:
                    exit_code = main(["init", "--path", str(repo), "--no-hooks"])
                    mock_global.return_value.register.assert_called_once()

            captured = capsys.readouterr()
            assert exit_code == 0
            assert (repo / ".claude-wiki.lock").exists()
            assert not (repo / ".claude" / "settings.local.json").exists()
            assert "hooks skipped" in captured.out.lower()

    def test_init_global_succeeds_when_global_hooks_exist(self, capsys):
        """kb init --global succeeds and rewrites global settings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._install_global_hooks(Path(tmpdir))

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager") as mock_global:
                    exit_code = main(["init", "--path", str(repo), "--global"])
                    mock_global.return_value.register.assert_called_once()

            captured = capsys.readouterr()
            assert exit_code == 0
            assert not (repo / ".claude" / "settings.local.json").exists()
            global_settings = Path(tmpdir) / ".claude" / "settings.json"
            assert global_settings.exists()
            data = json.loads(global_settings.read_text())
            assert "claude-wiki-hook" in json.dumps(data)
            assert "hooks skipped" not in captured.out.lower()

    def test_init_default_succeeds_with_unrelated_global_hooks(self):
        """kb init installs repo-local hooks when global settings lack claude-wiki hooks."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            (claude_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "hooks": {
                            "SessionStart": [
                                {
                                    "hooks": [
                                        {"type": "command", "command": "echo unrelated"}
                                    ]
                                }
                            ]
                        }
                    }
                )
            )

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo)])

            assert exit_code == 0
            assert (repo / ".claude" / "settings.local.json").exists()

    def test_init_kb_dir_user_flag(self):
        """--kb-dir user writes lock with user mode and canonical XDG daily path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            expected_daily = (
                Path(user_data_dir("claude-wiki-daily", appauthor=False))
                / "local"
                / "my-project"
            )

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    with patch("sys.stdin.isatty", return_value=True):
                        with patch("builtins.input") as mock_input:
                            exit_code = main(
                                ["init", "--path", str(repo), "--kb-dir", "user"]
                            )
                            assert exit_code == 0
                            mock_input.assert_not_called()

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["kb_dir"] == "user"
            assert data["daily_dir"] == str(expected_daily)

    def test_init_kb_dir_project_flag(self):
        """--kb-dir project writes lock with project mode and repo-local daily path."""
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
                            exit_code = main(
                                ["init", "--path", str(repo), "--kb-dir", "project"]
                            )
                            assert exit_code == 0
                            mock_input.assert_not_called()

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["kb_dir"] == "project"
            assert data["daily_dir"] == ".claude/daily"

    def test_init_kb_dir_user_daily_dir_override(self):
        """--kb-dir user with --daily-dir uses the explicit daily path."""
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
                            exit_code = main(
                                [
                                    "init",
                                    "--path",
                                    str(repo),
                                    "--kb-dir",
                                    "user",
                                    "--daily-dir",
                                    "/tmp/custom-daily",
                                ]
                            )
                            assert exit_code == 0
                            mock_input.assert_not_called()

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["kb_dir"] == "user"
            assert data["daily_dir"] == "/tmp/custom-daily"

    def test_init_kb_dir_and_daily_dir_absolute(self):
        """Absolute --kb-dir and --daily-dir values are stored as-is."""
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
                            exit_code = main(
                                [
                                    "init",
                                    "--path",
                                    str(repo),
                                    "--kb-dir",
                                    "/tmp/wiki",
                                    "--daily-dir",
                                    "/tmp/daily",
                                ]
                            )
                            assert exit_code == 0
                            mock_input.assert_not_called()

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["kb_dir"] == "/tmp/wiki"
            assert data["daily_dir"] == "/tmp/daily"

    def test_init_default_without_new_flags_keeps_project_mode(self):
        """init without --kb-dir/--daily-dir keeps existing project-mode behavior."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                with patch("claude_wiki.cli.GlobalIndexManager"):
                    exit_code = main(["init", "--path", str(repo)])
                    assert exit_code == 0

            data = json.loads((repo / ".claude-wiki.lock").read_text())
            assert data["kb_dir"] == "project"
            assert data["daily_dir"] == ".claude/daily"

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
                        "layout_version": "2",
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
                        "layout_version": "2",
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


class TestInitLegacyHandling:
    """init refuses to operate on a legacy lock until migration is run."""

    def test_init_prints_error_and_returns_one_for_legacy_lock(self, capsys):
        """A lock with layout_version '1' makes init tell the user to migrate."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "my-project",
                        "repo_owner": "local",
                        "layout_version": "1",
                        "kb_dir": "project",
                        "daily_dir": "daily",
                        "reports_dir": "reports",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )

            with patch("claude_wiki.cli.GlobalIndexManager"):
                exit_code = main(["init", "--path", str(repo)])

            captured = capsys.readouterr()
            assert exit_code == 1
            assert "Legacy layout version detected" in captured.err
            assert "claude-wiki migrate" in captured.err


class TestMigrateCommand:
    """Tests for claude-wiki migrate with path override flags."""

    def _bootstrap_repo(self, repo: Path) -> None:
        """Create lock, knowledge, and daily directories."""
        config = {
            "repo_name": repo.name,
            "repo_owner": "local",
            "layout_version": "2",
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

    def _bootstrap_project_mode_repo(self, repo: Path) -> None:
        """Create a project-mode lock plus knowledge, daily, and state dirs."""
        config = {
            "repo_name": repo.name,
            "repo_owner": "local",
            "layout_version": "2",
            "kb_dir": "project",
            "daily_dir": ".claude/daily",
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(config))
        (repo / ".claude" / "knowledge").mkdir(parents=True)
        (repo / ".claude" / "knowledge" / f"{repo.name}.md").write_text("# Index")
        (repo / ".claude" / "daily").mkdir(parents=True)
        (repo / ".claude" / "daily" / "2024-01-01.md").write_text("log")
        (repo / ".claude" / "state").mkdir(parents=True)
        (repo / ".claude" / "state" / "state.json").write_text("{}")
        (repo / ".claude" / "state" / "logs").mkdir(parents=True)
        (repo / ".claude" / "state" / "logs" / "compile.log").write_text("log")

    def _bootstrap_user_mode_repo(self, repo: Path, home: Path) -> None:
        """Create a user-mode lock plus XDG knowledge, daily, and state dirs."""
        vault = home / ".local" / "share" / "claude-wiki-vault" / "local" / repo.name
        daily = home / ".local" / "share" / "claude-wiki-daily" / "local" / repo.name
        state = (
            home / ".local" / "state" / "claude-wiki" / "repos" / "local" / repo.name
        )
        config = {
            "repo_name": repo.name,
            "repo_owner": "local",
            "layout_version": "2",
            "kb_dir": "user",
            "daily_dir": str(daily),
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(config))
        vault.mkdir(parents=True)
        (vault / f"{repo.name}.md").write_text("# Index")
        daily.mkdir(parents=True)
        (daily / "2024-01-01.md").write_text("log")
        state.mkdir(parents=True)
        (state / "state.json").write_text("{}")
        (state / "logs").mkdir(parents=True)
        (state / "logs" / "compile.log").write_text("log")

    def test_migrate_kb_dir_user_mode_moves_kb_daily_and_state(self, tmp_path):
        """--kb-dir user on a project-mode repo moves all three data dirs."""
        home = tmp_path / "home"
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        self._bootstrap_project_mode_repo(repo)

        with patch("claude_wiki.cli.GlobalIndexManager"):
            exit_code = main(["migrate", "--path", str(repo), "--kb-dir", "user"])

        assert exit_code == 0
        new_kb = home / ".local" / "share" / "claude-wiki-vault" / "local" / repo.name
        new_daily = (
            home / ".local" / "share" / "claude-wiki-daily" / "local" / repo.name
        )
        new_state = (
            home / ".local" / "state" / "claude-wiki" / "repos" / "local" / repo.name
        )
        assert (new_kb / f"{repo.name}.md").exists()
        assert (new_daily / "2024-01-01.md").exists()
        assert (new_state / "state.json").exists()
        assert (new_state / "logs" / "compile.log").exists()
        assert not (repo / ".claude" / "knowledge").exists()
        assert not (repo / ".claude" / "daily").exists()
        assert not (repo / ".claude" / "state").exists()
        lock = json.loads((repo / ".claude-wiki.lock").read_text())
        assert lock["kb_dir"] == "user"
        assert lock["daily_dir"] == str(new_daily)

    def test_migrate_kb_dir_project_mode_moves_kb_daily_and_state_back(self, tmp_path):
        """--kb-dir project on a user-mode repo moves all three data dirs back."""
        home = tmp_path / "home"
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        self._bootstrap_user_mode_repo(repo, home)

        with patch("claude_wiki.cli.GlobalIndexManager"):
            exit_code = main(["migrate", "--path", str(repo), "--kb-dir", "project"])

        assert exit_code == 0
        assert (repo / ".claude" / "knowledge" / f"{repo.name}.md").exists()
        assert (repo / ".claude" / "daily" / "2024-01-01.md").exists()
        assert (repo / ".claude" / "state" / "state.json").exists()
        assert (repo / ".claude" / "state" / "logs" / "compile.log").exists()
        assert not (
            home / ".local" / "share" / "claude-wiki-vault" / "local" / repo.name
        ).exists()
        assert not (
            home / ".local" / "share" / "claude-wiki-daily" / "local" / repo.name
        ).exists()
        assert not (
            home / ".local" / "state" / "claude-wiki" / "repos" / "local" / repo.name
        ).exists()
        lock = json.loads((repo / ".claude-wiki.lock").read_text())
        assert lock["kb_dir"] == "project"
        assert lock["daily_dir"] == ".claude/daily"

    def test_migrate_kb_dir_user_mode_dry_run_reports_all_three(self, tmp_path, capsys):
        """--dry-run --kb-dir user reports all three prospective moves."""
        home = tmp_path / "home"
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        self._bootstrap_project_mode_repo(repo)

        with patch("claude_wiki.cli.GlobalIndexManager"):
            exit_code = main(
                ["migrate", "--path", str(repo), "--kb-dir", "user", "--dry-run"]
            )

        captured = capsys.readouterr()
        assert exit_code == 0
        assert (repo / ".claude" / "knowledge").exists()
        assert (repo / ".claude" / "daily").exists()
        assert (repo / ".claude" / "state").exists()
        new_kb = home / ".local" / "share" / "claude-wiki-vault" / "local" / repo.name
        new_daily = (
            home / ".local" / "share" / "claude-wiki-daily" / "local" / repo.name
        )
        new_state = (
            home / ".local" / "state" / "claude-wiki" / "repos" / "local" / repo.name
        )
        assert "Would move kb_dir" in captured.out
        assert "Would move daily_dir" in captured.out
        assert "Would move state_dir" in captured.out
        assert str(new_kb) in captured.out
        assert str(new_daily) in captured.out
        assert str(new_state) in captured.out

    def test_migrate_kb_dir_user_state_failure_rolls_back(self, tmp_path, monkeypatch):
        """A failed state move rolls back already-completed kb/daily moves."""
        import shutil

        home = tmp_path / "home"
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        self._bootstrap_project_mode_repo(repo)

        new_state = (
            home / ".local" / "state" / "claude-wiki" / "repos" / "local" / repo.name
        )
        original_move = shutil.move

        def _failing_move(src, dst, **kwargs):
            if Path(dst).resolve() == new_state.resolve():
                raise PermissionError(f"mock failure moving {src} -> {dst}")
            return original_move(src, dst, **kwargs)

        monkeypatch.setattr(shutil, "move", _failing_move)

        with patch("claude_wiki.cli.GlobalIndexManager"):
            exit_code = main(["migrate", "--path", str(repo), "--kb-dir", "user"])

        assert exit_code == 1
        assert (repo / ".claude" / "knowledge" / f"{repo.name}.md").exists()
        assert (repo / ".claude" / "daily" / "2024-01-01.md").exists()
        assert (repo / ".claude" / "state" / "state.json").exists()
        assert not (
            home / ".local" / "share" / "claude-wiki-vault" / "local" / repo.name
        ).exists()
        assert not (
            home / ".local" / "share" / "claude-wiki-daily" / "local" / repo.name
        ).exists()
        assert not new_state.exists()

    def test_migrate_absolute_kb_dir_preserves_daily_and_state(self, tmp_path):
        """An absolute --kb-dir only moves the kb_dir unless --daily-dir is given."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        self._bootstrap_project_mode_repo(repo)

        custom_kb = tmp_path / "custom-kb"

        with patch("claude_wiki.cli.GlobalIndexManager"):
            exit_code = main(
                ["migrate", "--path", str(repo), "--kb-dir", str(custom_kb)]
            )

        assert exit_code == 0
        assert (custom_kb / f"{repo.name}.md").exists()
        assert (repo / ".claude" / "daily" / "2024-01-01.md").exists()
        assert (repo / ".claude" / "state" / "state.json").exists()
        assert not (repo / ".claude" / "knowledge").exists()
        lock = json.loads((repo / ".claude-wiki.lock").read_text())
        assert lock["kb_dir"] == str(custom_kb)
        assert lock["daily_dir"] == ".claude/daily"


class TestMigrateLegacyHandling:
    """migrate upgrades a legacy lock before performing path-change migration."""

    def test_migrate_legacy_project_mode_then_no_changes(self, capsys, tmp_path):
        """A project-mode legacy lock is upgraded and reports no path migration."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude-wiki.lock").write_text(
            json.dumps(
                {
                    "repo_name": repo.name,
                    "repo_owner": "local",
                    "layout_version": "1",
                    "kb_dir": "project",
                    "daily_dir": ".claude/daily",
                    "reports_dir": "reports",
                    "timezone": "UTC",
                    "compile_after_hour": 18,
                }
            )
        )
        kb_root = repo / ".claude" / "knowledge"
        kb_root.mkdir(parents=True)
        (kb_root / f"{repo.name}.md").write_text("# Index")
        state_dir = repo / ".claude" / "state"
        state_dir.mkdir(parents=True)
        (state_dir / "state.json").write_text('{"hash": "abc"}')

        with patch("claude_wiki.cli.GlobalIndexManager"):
            exit_code = main(["migrate", "--path", str(repo)])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No migration needed" in captured.out
        lock = json.loads((repo / ".claude-wiki.lock").read_text())
        assert lock["layout_version"] == "2"
        assert (state_dir / "state.json").read_text() == '{"hash": "abc"}'


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

    def test_register_commands_skips_broken_modules(self, monkeypatch, caplog):
        """Broken command modules are logged and skipped during discovery."""
        fake_subparsers = type("Subparsers", (), {"add_parser": lambda *a, **k: None})()
        handlers: dict[str, Any] = {}

        def fake_iter_modules(*_args, **_kwargs):
            yield (None, "claude_wiki.commands.broken", False)

        def fake_import_module(_name):
            raise ImportError("boom")

        monkeypatch.setattr(pkgutil, "iter_modules", fake_iter_modules)
        monkeypatch.setattr(importlib, "import_module", fake_import_module)

        with caplog.at_level("ERROR", logger="claude_wiki.cli"):
            _register_commands(fake_subparsers, handlers)

        assert handlers == {}
        assert "claude_wiki.commands.broken" in caplog.text
        assert "boom" in caplog.text

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
                    "layout_version": "2",
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
                    "layout_version": "2",
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
                    "layout_version": "2",
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
