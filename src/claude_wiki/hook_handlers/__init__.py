"""Hook event handlers — explicit registry (ADR-009 Phase 4.2)."""

from __future__ import annotations

_HANDLER_MODULES: list[str] = [
    "claude_wiki.hook_handlers.pre_compact",
    "claude_wiki.hook_handlers.session_end",
    "claude_wiki.hook_handlers.session_start",
]


def get_handler_modules() -> list[str]:
    """Return the explicit list of hook handler module import names."""
    return list(_HANDLER_MODULES)
