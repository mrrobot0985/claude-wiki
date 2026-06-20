"""Minimal stderr logging setup for claude-wiki hooks and CLI."""

from __future__ import annotations

import logging
import os
import sys


def configure_stderr_logging(level: int | None = None) -> None:
    """Ensure the claude_wiki logger emits to stderr.

    If ``CLAUDE_WIKI_DEBUG`` is set in the environment, use DEBUG; otherwise
    WARNING.  Safe to call repeatedly: existing stderr handlers are updated,
    not duplicated.
    """
    root = logging.getLogger("claude_wiki")
    if level is None:
        level = (
            logging.DEBUG if os.environ.get("CLAUDE_WIKI_DEBUG") else logging.WARNING
        )
    # Use a low logger level so child loggers can propagate their records to
    # other handlers (e.g. file logging set up later), while the stderr handler
    # filters by the requested level.
    root.setLevel(logging.DEBUG)

    for handler in list(root.handlers):
        if isinstance(handler, logging.StreamHandler) and handler.stream is sys.stderr:
            handler.setLevel(level)
            return

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter("%(name)s: %(levelname)s: %(message)s"))
    root.addHandler(handler)
