"""`claude-wiki register` — register an existing `.claude-wiki.lock` with the global index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from claude_wiki.config import ConfigManager
from claude_wiki.errors import ConfigError, RepoNotFoundError
from claude_wiki.global_index import GlobalIndexManager


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    """Register the ``register`` subcommand."""
    parser = subparsers.add_parser(
        "register",
        help="Register an existing .claude-wiki.lock with the global KB index",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Repo root containing .claude-wiki.lock (default: auto-detect)",
    )
    handlers["register"] = _handle_register


def _handle_register(args: argparse.Namespace) -> int:
    """Execute the register command."""
    detector = ConfigManager()
    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    marker = repo_root / ".claude-wiki.lock"
    if not marker.exists():
        print(
            f"Error: No .claude-wiki.lock found at {repo_root.resolve()}. "
            "Run 'claude-wiki init' first.",
            file=sys.stderr,
        )
        return 1

    try:
        config = detector.load(repo_root)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    kb_root = detector.get_kb_root(repo_root, config)
    GlobalIndexManager().register(
        config.repo_name,
        config.repo_owner,
        kb_root,
        repo_root=repo_root,
    )

    print(f"Registered {config.repo_owner}/{config.repo_name} at {repo_root}")
    return 0
