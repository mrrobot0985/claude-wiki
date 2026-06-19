"""Public API surface."""

from claude_kb.cli import main
from claude_kb.hooks import main as hook_main

__all__ = ["main", "hook_main"]
