"""CLI subcommands — explicit registry (ADR-009 Phase 4.1)."""

from __future__ import annotations

_COMMAND_MODULES: list[str] = [
    "claude_wiki.commands.compile",
    "claude_wiki.commands.graph",
    "claude_wiki.commands.lint",
    "claude_wiki.commands.query",
    "claude_wiki.commands.register",
    "claude_wiki.commands.registry",
    "claude_wiki.commands.rename_catalog",
    "claude_wiki.commands.status",
    "claude_wiki.commands.tags",
]


def get_command_modules() -> list[str]:
    """Return the explicit list of command module import names."""
    return list(_COMMAND_MODULES)
