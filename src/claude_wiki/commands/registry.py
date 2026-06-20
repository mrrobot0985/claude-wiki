"""`claude-wiki registry` — manage the global knowledge-base registry."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
from pathlib import Path

from claude_wiki.global_index import GlobalIndexManager, RegistryEntry


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    """Register the ``registry`` subcommand group."""
    parser = subparsers.add_parser(
        "registry",
        help="Manage the global knowledge-base registry",
    )
    registry_subparsers = parser.add_subparsers(dest="registry_command")

    list_parser = registry_subparsers.add_parser(
        "list", help="List every registered knowledge base"
    )
    list_parser.set_defaults(registry_command="list")

    show_parser = registry_subparsers.add_parser(
        "show", help="Show details for a single registered repo"
    )
    show_parser.set_defaults(registry_command="show")
    show_parser.add_argument("repo", help="Repository identifier as owner/repo")

    remove_parser = registry_subparsers.add_parser(
        "remove", help="Remove a repo from the global registry"
    )
    remove_parser.set_defaults(registry_command="remove")
    remove_parser.add_argument("repo", help="Repository identifier as owner/repo")
    remove_parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt",
    )

    clean_parser = registry_subparsers.add_parser(
        "clean", help="Evict stale registry entries"
    )
    clean_parser.set_defaults(registry_command="clean")

    handlers["registry"] = _handle_registry


def _handle_registry(args: argparse.Namespace) -> int:
    """Dispatch to the selected registry subcommand."""
    command: str | None = getattr(args, "registry_command", None)
    if command == "list":
        return _list_entries()
    if command == "show":
        return _show_entry(str(args.repo))
    if command == "remove":
        return _remove_entry(str(args.repo), yes=args.yes)
    if command == "clean":
        return _clean_entries()

    # Should never be reached because argparse enforces a subcommand.
    print("Error: No registry subcommand given.", file=sys.stderr)
    return 1


def _parse_repo_spec(repo: str) -> tuple[str, str] | None:
    """Validate and split an ``owner/repo`` identifier."""
    parts = repo.split("/")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        print(
            f"Error: Invalid repo '{repo}'. Expected owner/repo.",
            file=sys.stderr,
        )
        return None
    return parts[0], parts[1]


def _kb_mode_label(entry: RegistryEntry) -> str:
    """Derive the KB mode label for an entry."""
    if entry.repo_root is None:
        return "unknown"
    return GlobalIndexManager()._derive_kb_mode_label(Path(entry.repo_root))


def _format_entry(entry: RegistryEntry) -> str:
    """Return a human-readable rendering of a registry entry."""
    mode = _kb_mode_label(entry)
    lines = [
        f"{entry.repo_owner}/{entry.repo_name} ({mode})",
        f"  kb_root: {entry.kb_root}",
        f"  repo_root: {entry.repo_root or 'n/a'}",
        f"  articles: {entry.articles} | last_compiled: {entry.last_compiled or 'never'}",
    ]
    return "\n".join(lines)


def _list_entries() -> int:
    """Print every registered repo."""
    entries = GlobalIndexManager().list_entries()
    if entries:
        print("\n\n".join(_format_entry(e) for e in entries))
    return 0


def _show_entry(repo: str) -> int:
    """Print one registry entry."""
    spec = _parse_repo_spec(repo)
    if spec is None:
        return 1
    owner, name = spec
    for entry in GlobalIndexManager().list_entries():
        if entry.repo_owner == owner and entry.repo_name == name:
            print(_format_entry(entry))
            return 0
    print(f"Error: {owner}/{name} not found in registry.", file=sys.stderr)
    return 1


def _remove_entry(repo: str, *, yes: bool) -> int:
    """Remove a registry entry after optional confirmation."""
    spec = _parse_repo_spec(repo)
    if spec is None:
        return 1
    owner, name = spec
    mgr = GlobalIndexManager()
    if not any(
        e.repo_owner == owner and e.repo_name == name for e in mgr.list_entries()
    ):
        print(f"Error: {owner}/{name} not found in registry.", file=sys.stderr)
        return 1

    if not yes:
        if not sys.stdin.isatty():
            print(
                f"Error: Refusing to remove {owner}/{name} without --yes in a non-interactive terminal.",
                file=sys.stderr,
            )
            return 1
        answer = (
            input(f"Remove {owner}/{name} from the registry? [y/N] ").strip().lower()
        )
        if answer not in {"y", "yes"}:
            print("Aborted.", file=sys.stderr)
            return 1

    mgr.unregister(name, owner)
    print(f"Removed {owner}/{name} from registry.")
    return 0


def _clean_entries() -> int:
    """Evict stale registry entries and print what was removed."""
    evicted = GlobalIndexManager().sanitize()
    if evicted:
        for entry in evicted:
            print(f"Evicted {entry.repo_owner}/{entry.repo_name}")
    else:
        print("No stale registry entries found.")
    return 0
