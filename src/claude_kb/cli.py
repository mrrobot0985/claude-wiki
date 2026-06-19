"""argparse CLI — user-facing commands."""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_kb.errors import RepoNotFoundError
from claude_kb.factories import DefaultConfigResolver
from claude_kb.models import ProjectConfig

_Handler = Callable[[argparse.Namespace], int]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="claude-wiki")
    subparsers = parser.add_subparsers(dest="command")

    # init
    init_parser = subparsers.add_parser("init", help="Initialise KB for this repo")
    init_parser.add_argument(
        "--path", type=Path, help="Repo root (default: auto-detect)"
    )
    init_parser.add_argument(
        "--force", action="store_true", help="Overwrite existing marker"
    )

    # Dynamically register subcommands from commands/ modules
    handlers: dict[str, _Handler] = {}
    _register_commands(subparsers, handlers)

    args = parser.parse_args(argv)

    if args.command is None:
        parser.print_help()
        return 1

    if args.command == "init":
        return _init(args)

    handler = handlers.get(args.command)
    if handler:
        return handler(args)

    print(f"Command '{args.command}' not yet implemented.", file=sys.stderr)
    return 1


def _register_commands(
    subparsers: Any,
    handlers: dict[str, _Handler],
) -> None:
    """Auto-discover and register command modules from commands/."""
    from claude_kb import commands as commands_pkg

    for _finder, name, _ispkg in pkgutil.iter_modules(
        commands_pkg.__path__, commands_pkg.__name__ + "."
    ):
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "register"):
                mod.register(subparsers, handlers)
        except Exception:
            # Skip broken command modules during discovery
            continue


def _init(args: argparse.Namespace) -> int:
    """Orchestrate ConfigManager + HookRegistrar to bootstrap a repo."""
    detector, loader, registrar = DefaultConfigResolver.build()

    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    marker = repo_root / ".claude-wiki.json"
    if marker.exists() and not args.force:
        print(
            f"KB already initialised at {repo_root}. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 0

    config = loader.load(repo_root)
    if args.force or not marker.exists():
        config = ProjectConfig(
            repo_name=repo_root.name,
            repo_owner=config.repo_owner,
            kb_dir=config.kb_dir,
            daily_dir=config.daily_dir,
            timezone=config.timezone,
        )

    loader.write(repo_root, config)
    registrar.install_hooks(repo_root, config)

    print(f"Initialised KB for {config.repo_name} at {repo_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
