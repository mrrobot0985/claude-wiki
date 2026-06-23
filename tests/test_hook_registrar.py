"""Unit tests for DefaultHookRegistrar — global settings.json mutation."""

import json
import tempfile
from pathlib import Path

from claude_wiki.factories import DefaultHookRegistrar
from claude_wiki.models import ProjectConfig


class TestDefaultHookRegistrar:
    """Tests for idempotent global settings installation."""

    def test_install_creates_settings(self):
        """Create settings file at the given path if absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            settings_path = repo / ".claude" / "settings.local.json"

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")
            registrar.install_hooks(repo, config, settings_path=settings_path)

            assert settings_path.exists()
            data = json.loads(settings_path.read_text())
            assert "hooks" in data
            assert "SessionStart" in data["hooks"]
            assert "SessionEnd" in data["hooks"]
            assert "PreCompact" in data["hooks"]

    def test_install_preserves_existing_keys(self):
        """Merge with pre-existing settings file (e.g. statusLine, env)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            settings_path = repo / ".claude" / "settings.local.json"
            settings_path.parent.mkdir(parents=True, exist_ok=True)
            settings_path.write_text(
                json.dumps(
                    {
                        "statusLine": {"type": "command", "command": "echo test"},
                        "env": {"FOO": "bar"},
                    }
                )
            )

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")
            registrar.install_hooks(repo, config, settings_path=settings_path)

            settings = json.loads(settings_path.read_text())
            assert settings["statusLine"]["command"] == "echo test"
            assert settings["env"]["FOO"] == "bar"
            assert len(settings["hooks"]) == 3

    def test_install_idempotent(self):
        """Re-running does not duplicate hook entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            settings_path = repo / ".claude" / "settings.local.json"

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")
            registrar.install_hooks(repo, config, settings_path=settings_path)
            registrar.install_hooks(repo, config, settings_path=settings_path)

            settings = json.loads(settings_path.read_text())
            assert len(settings["hooks"]) == 3

    def test_hook_command_uses_valid_uvx_syntax(self):
        """Commands must use `uvx --from <pkg> <cmd>` syntax, not bare `uvx <pkg> <cmd>`."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            settings_path = repo / ".claude" / "settings.local.json"

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")
            registrar.install_hooks(repo, config, settings_path=settings_path)

            settings = json.loads(settings_path.read_text())
            for event in ("SessionStart", "SessionEnd", "PreCompact"):
                command = settings["hooks"][event][0]["hooks"][0]["command"]
                parts = command.split()
                # Expect: uvx --from claude-wiki claude-wiki-hook <Event>
                assert parts[0] == "uvx"
                assert parts[1] == "--from"
                assert parts[2] == "claude-wiki"
                assert parts[3] == "claude-wiki-hook"
                assert parts[4] == event
