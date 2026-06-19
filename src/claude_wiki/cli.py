"""argparse CLI — user-facing commands."""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import pkgutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError
from claude_wiki.factories import DefaultConfigResolver
from claude_wiki.global_index import GlobalIndexManager
from claude_wiki.models import MigrationResult, ProjectConfig

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
    init_parser.add_argument(
        "--global",
        dest="global_flag",
        action="store_true",
        help="Install hooks into ~/.claude/settings.json instead of repo-local .claude/settings.local.json",
    )

    # migrate
    migrate_parser = subparsers.add_parser(
        "migrate", help="Check and migrate data when config paths change"
    )
    migrate_parser.add_argument(
        "--path", type=Path, help="Repo root (default: auto-detect)"
    )
    migrate_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would move without touching disk",
    )
    migrate_parser.add_argument(
        "--kb-dir", type=Path, help="Override knowledge base directory"
    )
    migrate_parser.add_argument(
        "--daily-dir", type=Path, help="Override daily log directory"
    )
    migrate_parser.add_argument(
        "--reports-dir", type=Path, help="Override lint reports directory"
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
    if args.command == "migrate":
        return _migrate(args)

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
    from claude_wiki import commands as commands_pkg

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
    detector, loader, registrar, migrator = DefaultConfigResolver.build()
    assert isinstance(detector, ConfigManager)

    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    marker = repo_root / ".claude-wiki.lock"
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
            reports_dir=config.reports_dir,
            timezone=config.timezone,
        )

    # On first init there is no previous state, so no migration is attempted.
    result = migrator.check_and_migrate(repo_root, config, None, dry_run=False)
    if result.migrated:
        _print_migration_result(result)
    elif result.errors:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)

    loader.write(repo_root, config)

    if args.global_flag:
        settings_path = Path.home() / ".claude" / "settings.json"
    else:
        settings_path = repo_root / ".claude" / "settings.local.json"

    registrar.install_hooks(repo_root, config, settings_path=settings_path)

    target_label = "global" if args.global_flag else "repo-local"
    print(f"Installed hooks into {target_label} settings: {settings_path}")

    kb_root = detector.get_kb_root(config)
    GlobalIndexManager().register(
        config.repo_name, config.repo_owner, kb_root, repo_root=repo_root
    )

    print(f"Initialised KB for {config.repo_name} at {repo_root}")
    return 0


def _migrate(args: argparse.Namespace) -> int:
    """Check for path changes and migrate data."""
    detector, loader, _registrar, migrator = DefaultConfigResolver.build()

    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    if not (repo_root / ".claude-wiki.lock").exists():
        print(
            "Error: No .claude-wiki.lock found. Run 'claude-wiki init' first.",
            file=sys.stderr,
        )
        return 1

    previous = loader.load(repo_root)
    overrides: dict[str, Any] = {}
    if args.kb_dir:
        overrides["kb_dir"] = args.kb_dir
    if args.daily_dir:
        overrides["daily_dir"] = args.daily_dir
    if args.reports_dir:
        overrides["reports_dir"] = args.reports_dir
    config = dataclasses.replace(previous, **overrides) if overrides else previous

    if previous == config:
        print("No migration needed — paths are unchanged.")
        return 0

    result = migrator.check_and_migrate(
        repo_root, config, previous, dry_run=args.dry_run
    )

    if not result.migrated and not result.errors:
        print("No migration needed — paths are unchanged.")
        if not args.dry_run and overrides:
            loader.write(repo_root, config)
            print("State updated.")
        return 0

    _print_migration_result(result)

    if result.errors:
        return 1

    if not args.dry_run:
        loader.write(repo_root, config)
        if result.new_kb_dir:
            GlobalIndexManager().register(
                config.repo_name,
                config.repo_owner,
                result.new_kb_dir,
                repo_root=repo_root,
            )
        print("State updated.")

    return 0


def _print_migration_result(result: MigrationResult) -> None:
    """Pretty-print migration result."""
    if result.migrated:
        print("Migration performed:")
        if result.old_kb_dir and result.new_kb_dir:
            print(f"  kb_dir: {result.old_kb_dir} -> {result.new_kb_dir}")
        if result.old_daily_dir and result.new_daily_dir:
            print(f"  daily_dir: {result.old_daily_dir} -> {result.new_daily_dir}")
    for w in result.warnings:
        print(f"  Warning: {w}")
    for e in result.errors:
        print(f"  Error: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
