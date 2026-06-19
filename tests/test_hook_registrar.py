"""Unit tests for DefaultHookRegistrar — global settings.json mutation."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from claude_kb.factories import DefaultHookRegistrar
from claude_kb.models import ProjectConfig


class TestHookRegistrar:
    """Tests for idempotent global settings installation."""

    def test_install_creates_settings(self):
        """Create ~/.claude/settings.json if absent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                registrar.install_hooks(repo, config)

            settings = claude_dir / "settings.json"
            assert settings.exists()
            data = json.loads(settings.read_text())
            assert "hooks" in data
            assert "SessionStart" in data["hooks"]
            assert "SessionEnd" in data["hooks"]
            assert "PreCompact" in data["hooks"]

    def test_install_preserves_existing_keys(self):
        """Merge with pre-existing settings.json (e.g. statusLine, env)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()
            (claude_dir / "settings.json").write_text(
                json.dumps(
                    {
                        "statusLine": {"type": "command", "command": "echo test"},
                        "env": {"FOO": "bar"},
                    }
                )
            )

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                registrar.install_hooks(repo, config)

            settings = json.loads((claude_dir / "settings.json").read_text())
            assert settings["statusLine"]["command"] == "echo test"
            assert settings["env"]["FOO"] == "bar"
            assert len(settings["hooks"]) == 3

    def test_install_idempotent(self):
        """Re-running does not duplicate hook entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            claude_dir = Path(tmpdir) / ".claude"
            claude_dir.mkdir()

            registrar = DefaultHookRegistrar()
            config = ProjectConfig(repo_name="my-project")

            with patch.dict("os.environ", {"HOME": tmpdir}, clear=False):
                registrar.install_hooks(repo, config)
                registrar.install_hooks(repo, config)

            settings = json.loads((claude_dir / "settings.json").read_text())
            assert len(settings["hooks"]) == 3
