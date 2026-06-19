"""Public API surface."""

from claude_wiki.cli import main
from claude_wiki.hooks import main as hook_main

__all__ = ["main", "hook_main"]
