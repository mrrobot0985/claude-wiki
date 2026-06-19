"""Hook entry point — minimal, fast, called by Claude Code."""

from __future__ import annotations

import importlib
import pkgutil
import sys
from collections.abc import Callable

_Handler = Callable[[list[str]], int]


def main(argv: list[str] | None = None) -> int:
    """kb-hook <Event>"""
    if not argv:
        argv = sys.argv[1:]

    if len(argv) < 1:
        print("Usage: kb-hook SessionStart|SessionEnd|PreCompact", file=sys.stderr)
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
    from claude_kb import hook_handlers as handlers_pkg

    for _finder, name, _ispkg in pkgutil.iter_modules(
        handlers_pkg.__path__, handlers_pkg.__name__ + "."
    ):
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "register"):
                mod.register(handlers)
        except Exception:
            continue
