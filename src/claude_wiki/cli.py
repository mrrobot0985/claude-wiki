"""argparse CLI — user-facing commands."""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import logging
import pkgutil
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_wiki import interactive
from claude_wiki.config import ConfigManager, default_daily_dir
from claude_wiki.errors import ConfigError, RepoNotFoundError
from claude_wiki.factories import DefaultConfigResolver
from claude_wiki.global_index import GlobalIndexManager
from claude_wiki.hook_detect import (
    global_claude_settings_path,
    settings_has_claude_wiki_hooks,
)
from claude_wiki.logging_setup import configure_stderr_logging
from claude_wiki.migration import MigrationManager
from claude_wiki.models import MigrationResult

logger = logging.getLogger(__name__)


def _resolve_kb_mode(kb_dir: Path) -> str:
    """Return 'user' or 'project' for mode strings, otherwise 'custom'."""
    mode = str(kb_dir)
    if mode in ("user", "project"):
        return mode
    return "custom"


_Handler = Callable[[argparse.Namespace], int]


def _build_parser() -> tuple[argparse.ArgumentParser, dict[str, _Handler]]:
    """Build the argparse parser exactly as the live CLI uses it.

    Factored out so completion generators and tests can introspect the
    parser without duplicating its declaration.
    """
    # Lazy import: `claude_wiki.cli` is imported by `claude_wiki/__init__.py`
    # before `__version__` is bound there, so a top-level import would cycle.
    from claude_wiki import __version__

    parser = argparse.ArgumentParser(prog="claude-wiki")
    parser.add_argument(
        "-v",
        "--version",
        action="version",
        version=f"claude-wiki {__version__}",
    )
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
    init_parser.add_argument(
        "--no-hooks",
        dest="no_hooks",
        action="store_true",
        help="Skip Claude Code hook installation (settings files are not created)",
    )
    init_parser.add_argument(
        "--kb-dir",
        dest="kb_dir",
        type=Path,
        help='KB directory mode: "project", "user", or a custom path',
    )
    init_parser.add_argument(
        "--daily-dir",
        dest="daily_dir",
        type=Path,
        help="Daily log directory (default depends on --kb-dir mode)",
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

    return parser, handlers


def main(argv: list[str] | None = None) -> int:
    configure_stderr_logging()

    parser, handlers = _build_parser()

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


def _is_interactive(args: argparse.Namespace) -> bool:
    """Return True when stdin is a TTY and no config-disabling flags are set."""
    if not sys.stdin.isatty():
        return False
    if args.global_flag:
        return False
    if args.no_hooks:
        return False
    if args.kb_dir is not None:
        return False
    if args.daily_dir is not None:
        return False
    return True


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
        except Exception as exc:
            logger.error("Failed to load command module %s: %s", name, exc)


def _init(args: argparse.Namespace) -> int:
    """Orchestrate ConfigManager + HookRegistrar to bootstrap a repo."""
    detector, loader, registrar, migrator, owner_resolver = (
        DefaultConfigResolver.build()
    )
    assert isinstance(detector, ConfigManager)

    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    marker = repo_root / ".claude-wiki.lock"
    try:
        defaults = loader.load(repo_root)
    except ConfigError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    inferred_owner = owner_resolver.infer_repo_owner(repo_root)

    needs_update = inferred_owner != "local" or args.force or not marker.exists()

    if not needs_update:
        print(
            f"KB already initialised at {repo_root}. Use --force to overwrite.",
            file=sys.stderr,
        )
        return 0

    defaults = dataclasses.replace(
        defaults,
        repo_name=repo_root.name,
        repo_owner=inferred_owner,
    )

    interactive_mode = _is_interactive(args)
    if interactive_mode and marker.exists() and args.force:
        if not interactive.confirm("Overwrite existing .claude-wiki.lock"):
            print("Aborted.", file=sys.stderr)
            return 1

    if interactive_mode:
        try:
            config, use_global_hooks = interactive.configure(repo_root, defaults)
        except KeyboardInterrupt:
            print("\nAborted.", file=sys.stderr)
            return 1
    else:
        overrides: dict[str, Any] = {}
        if args.kb_dir is not None:
            overrides["kb_dir"] = args.kb_dir
        if args.daily_dir is not None:
            overrides["daily_dir"] = args.daily_dir
        if args.daily_dir is None and args.kb_dir is not None:
            kb_mode = str(args.kb_dir)
            overrides["daily_dir"] = default_daily_dir(
                kb_mode, defaults.repo_owner, defaults.repo_name
            )
        config = dataclasses.replace(defaults, **overrides) if overrides else defaults
        use_global_hooks = args.global_flag

    if not args.no_hooks and not use_global_hooks:
        global_settings = global_claude_settings_path()
        if settings_has_claude_wiki_hooks(global_settings):
            print(
                "Error: Global claude-wiki hooks are already installed in "
                f"{global_settings}. Run 'claude-wiki init --no-hooks' to skip "
                "repo-local hooks or 'claude-wiki init --global' to rewrite the "
                "global settings.",
                file=sys.stderr,
            )
            return 1

    # On first init there is no previous state, so no migration is attempted.
    result = migrator.check_and_migrate(repo_root, config, None, dry_run=False)
    if result.migrated:
        _print_migration_result(result)
    elif result.errors:
        for err in result.errors:
            print(f"Error: {err}", file=sys.stderr)

    loader.write(repo_root, config)

    if args.no_hooks:
        print(
            "Hooks skipped; run 'claude-wiki init' without --no-hooks to install them later."
        )
    else:
        if use_global_hooks:
            settings_path = global_claude_settings_path()
        else:
            settings_path = repo_root / ".claude" / "settings.local.json"

        registrar.install_hooks(repo_root, config, settings_path=settings_path)

        target_label = "global" if use_global_hooks else "repo-local"
        print(f"Installed hooks into {target_label} settings: {settings_path}")

    kb_root = detector.get_kb_root(repo_root, config)
    GlobalIndexManager().register(
        config.repo_name, config.repo_owner, kb_root, repo_root=repo_root
    )

    print(f"Initialised KB for {config.repo_name} at {repo_root}")
    return 0


def _migrate(args: argparse.Namespace) -> int:
    """Check for path changes and migrate data."""
    detector, loader, _registrar, migrator, _owner_resolver = (
        DefaultConfigResolver.build()
    )

    start = args.path if args.path else Path.cwd()

    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    marker = repo_root / ".claude-wiki.lock"
    if not marker.exists():
        print(
            "Error: No .claude-wiki.lock found. Run 'claude-wiki init' first.",
            file=sys.stderr,
        )
        return 1

    try:
        raw_data = json.loads(marker.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"Error: Corrupt lock file {marker}: {exc}", file=sys.stderr)
        return 1

    if raw_data.get("layout_version") in (None, "", "1"):
        if isinstance(detector, ConfigManager) and isinstance(
            migrator, MigrationManager
        ):
            temp_config = detector._build_config(repo_root, raw_data)
            migrator.migrate_legacy_layout(repo_root, temp_config)

    previous = loader.load(repo_root)
    if args.reports_dir:
        print("Warning: --reports-dir is deprecated and ignored.", file=sys.stderr)

    overrides: dict[str, Any] = {}
    if args.kb_dir:
        overrides["kb_dir"] = args.kb_dir
    if args.daily_dir:
        overrides["daily_dir"] = args.daily_dir

    old_mode = _resolve_kb_mode(previous.kb_dir)
    new_mode = _resolve_kb_mode(overrides.get("kb_dir", previous.kb_dir))
    if (
        args.daily_dir is None
        and {old_mode, new_mode} == {"user", "project"}
        and old_mode != new_mode
    ):
        overrides["daily_dir"] = default_daily_dir(
            new_mode, previous.repo_owner, previous.repo_name
        )

    config = dataclasses.replace(previous, **overrides) if overrides else previous

    if previous == config:
        print("No migration needed — paths are unchanged.")
        return 0

    result = migrator.check_and_migrate(
        repo_root, config, previous, dry_run=args.dry_run
    )

    if not result.migrated and not result.errors:
        print("No migration needed — paths are unchanged.")
        # If moves were skipped because destinations were occupied, do not persist the
        # new paths; the user must resolve the conflict first.
        if not args.dry_run and overrides and not result.warnings:
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
        if result.old_state_dir and result.new_state_dir:
            print(f"  state_dir: {result.old_state_dir} -> {result.new_state_dir}")
    for w in result.warnings:
        print(f"  Warning: {w}")
    for e in result.errors:
        print(f"  Error: {e}")


if __name__ == "__main__":
    raise SystemExit(main())
