"""Wiring layer — builds concrete objects from protocols."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_wiki.config import ConfigManager
from claude_wiki.git_utils import infer_repo_owner
from claude_wiki.interfaces import (
    ConfigLoader,
    HookRegistrar,
    Migrator,
    RemoteOwnerResolver,
    RepoDetector,
)
from claude_wiki.migration import MigrationManager
from claude_wiki.models import ProjectConfig


class GitRemoteOwnerResolver(RemoteOwnerResolver):
    """Infers repo_owner from the origin remote using git."""

    def infer_repo_owner(self, repo_root: Path) -> str:
        return infer_repo_owner(repo_root)


class DefaultHookRegistrar(HookRegistrar):
    """Installs hooks into a Claude Code settings file with merge semantics."""

    def install_hooks(
        self,
        repo_root: Path,
        config: ProjectConfig,
        *,
        settings_path: Path,
    ) -> None:
        """Idempotently write hooks into the given settings file."""
        settings_path.parent.mkdir(parents=True, exist_ok=True)

        settings: dict[str, Any]
        if settings_path.exists():
            settings = json.loads(settings_path.read_text())
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
                            "command": "uvx --from claude-wiki claude-wiki-hook SessionStart",
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
                            "command": "uvx --from claude-wiki claude-wiki-hook SessionEnd",
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
                            "command": "uvx --from claude-wiki claude-wiki-hook PreCompact",
                            "timeout": 10,
                        }
                    ],
                }
            ],
        }

        # Merge: overwrite our events, preserve everything else
        for event, hook_list in our_hooks.items():
            settings["hooks"][event] = hook_list

        settings_path.write_text(json.dumps(settings, indent=2))


class DefaultConfigResolver:
    """Factory convenience — holds the production wiring."""

    @staticmethod
    def build() -> tuple[
        RepoDetector, ConfigLoader, HookRegistrar, Migrator, RemoteOwnerResolver
    ]:
        detector = ConfigManager()
        loader = detector  # same object implements both protocols
        registrar = DefaultHookRegistrar()
        migrator = MigrationManager(detector)
        owner_resolver = GitRemoteOwnerResolver()
        return detector, loader, registrar, migrator, owner_resolver
