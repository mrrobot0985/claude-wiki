"""Wiring layer — builds concrete objects from protocols."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_kb.config import ConfigManager
from claude_kb.interfaces import ConfigLoader, HookRegistrar, Migrator, RepoDetector
from claude_kb.migration import MigrationManager
from claude_kb.models import ProjectConfig


class DefaultHookRegistrar(HookRegistrar):
    """Installs hooks into ~/.claude/settings.json with merge semantics."""

    def install_hooks(self, repo_root: Path, config: ProjectConfig) -> None:
        """Idempotently write global settings.json."""
        claude_dir = Path.home() / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_file = claude_dir / "settings.json"

        settings: dict[str, Any]
        if settings_file.exists():
            settings = json.loads(settings_file.read_text())
        else:
            settings = {}

        if "hooks" not in settings:
            settings["hooks"] = {}

        our_hooks = {
            "SessionStart": [
                {
                    "matcher": "",
                    "hooks": [
                        {
                            "type": "command",
                            "command": "uvx claude-wiki claude-wiki-hook SessionStart",
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
                            "command": "uvx claude-wiki claude-wiki-hook SessionEnd",
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
                            "command": "uvx claude-wiki claude-wiki-hook PreCompact",
                            "timeout": 10,
                        }
                    ],
                }
            ],
        }

        # Merge: overwrite our events, preserve everything else
        for event, hook_list in our_hooks.items():
            settings["hooks"][event] = hook_list

        settings_file.write_text(json.dumps(settings, indent=2))


class DefaultConfigResolver:
    """Factory convenience — holds the production wiring."""

    @staticmethod
    def build() -> tuple[RepoDetector, ConfigLoader, HookRegistrar, Migrator]:
        detector = ConfigManager()
        loader = detector  # same object implements both protocols
        registrar = DefaultHookRegistrar()
        migrator = MigrationManager()
        return detector, loader, registrar, migrator
