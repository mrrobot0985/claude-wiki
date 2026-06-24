"""Tests for the wiring/factory layer."""

from __future__ import annotations

from pathlib import Path
from claude_wiki.factories import DefaultHookRegistrar
from claude_wiki.models import ProjectConfig


class TestDefaultHookRegistrar:
    """Hook installation writes valid, well-formed settings files."""

    def test_install_hooks_appends_trailing_newline(self, tmp_path: Path) -> None:
        """The settings JSON file must end with a newline."""
        registrar = DefaultHookRegistrar()
        settings_path = tmp_path / ".claude" / "settings.local.json"
        config = ProjectConfig(repo_name="test", repo_owner="local")

        registrar.install_hooks(tmp_path, config, settings_path=settings_path)

        assert settings_path.exists()
        raw = settings_path.read_bytes()
        assert raw.endswith(b"\n")
