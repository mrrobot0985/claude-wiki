"""Hook entry point — minimal, fast, called by Claude Code."""

from __future__ import annotations

import importlib
import logging
import pkgutil
import sys
from collections.abc import Callable

from claude_wiki.logging_setup import configure_stderr_logging

_Handler = Callable[[list[str]], int]

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    """claude-wiki-hook <Event>"""
    configure_stderr_logging()

    if not argv:
        argv = sys.argv[1:]

    if len(argv) < 1:
        print(
            "Usage: claude-wiki-hook SessionStart|SessionEnd|PreCompact",
            file=sys.stderr,
        )
        return 1

    event = argv[0]
    if event not in {"SessionStart", "SessionEnd", "PreCompact"}:
        print(f"Unknown hook event: {event}", file=sys.stderr)
        return 1

    # Auto-discover and dispatch to registered handlers
    handlers: dict[str, _Handler] = {}
    _load_handlers(handlers)

    handler = handlers.get(event)
    if handler:
        return handler(argv[1:])

    return 0


def _load_handlers(handlers: dict[str, _Handler]) -> None:
    """Auto-discover handler modules from hook_handlers/."""
    from claude_wiki import hook_handlers as handlers_pkg

    for _finder, name, _ispkg in pkgutil.iter_modules(
        handlers_pkg.__path__, handlers_pkg.__name__ + "."
    ):
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "register"):
                mod.register(handlers)
        except Exception as exc:
            logger.error("Failed to load hook handler %s: %s", name, exc)
