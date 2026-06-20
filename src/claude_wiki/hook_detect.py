"""Shared helpers for detecting claude-wiki hook installations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claude_wiki.factories import CLAUDE_WIKI_HOOK_COMMAND


def global_claude_settings_path() -> Path:
    """Return the path to Claude Code's global settings file."""
    return Path.home() / ".claude" / "settings.json"


def settings_has_claude_wiki_hooks(settings_path: Path) -> bool:
    """Return True if the settings file contains any claude-wiki hook command."""
    if not settings_path.exists():
        return False
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return _hooks_contain_command(data.get("hooks", {}))


def _hooks_contain_command(hooks: Any) -> bool:
    """Scan a hooks dictionary for commands containing the claude-wiki hook prefix."""
    if not isinstance(hooks, dict):
        return False
    for event_config in hooks.values():
        if not isinstance(event_config, list):
            continue
        for entry in event_config:
            if not isinstance(entry, dict):
                continue
            for hook in entry.get("hooks", []):
                if not isinstance(hook, dict):
                    continue
                command = hook.get("command", "")
                if isinstance(command, str) and CLAUDE_WIKI_HOOK_COMMAND in command:
                    return True
    return False
