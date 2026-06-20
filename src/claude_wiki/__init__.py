"""Public API surface."""

from __future__ import annotations

import importlib.metadata as _metadata

from claude_wiki.cli import main
from claude_wiki.hooks import main as hook_main

try:
    __version__ = _metadata.version("claude-wiki")
except _metadata.PackageNotFoundError:  # pragma: no cover - source tree fallback
    __version__ = "0.0.0+unknown"

__all__ = ["main", "hook_main", "__version__"]
