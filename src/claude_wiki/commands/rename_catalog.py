"""`claude-wiki rename-catalog` — rename index.md to {repo_name}.md."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from claude_wiki.catalog_utils import rewrite_index_wikilinks
from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    """Register the ``rename-catalog`` subcommand."""
    parser = subparsers.add_parser(
        "rename-catalog",
        help="Rename index.md to {repo_name}.md and rewrite article wikilinks",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be changed without touching disk",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="KB root path (defaults to current repo's KB)",
    )
    handlers["rename-catalog"] = _handle_rename_catalog


def _handle_rename_catalog(args: argparse.Namespace) -> int:
    """Execute the rename-catalog command."""
    kb_root: Path
    repo_name: str

    if args.path is not None:
        kb_root = args.path.expanduser().resolve(strict=False)
        # Infer repo_name from the directory name when --path is given
        repo_name = kb_root.name
    else:
        detector = ConfigManager()
        try:
            repo_root = detector.find_repo_root(Path.cwd())
        except RepoNotFoundError:
            print("Error: Not in a git repository.", file=sys.stderr)
            return 1
        config = detector.load(repo_root)
        kb_root = detector.get_kb_root(repo_root, config)
        repo_name = config.repo_name

    actions = _rename_catalog(kb_root, repo_name, dry_run=args.dry_run)
    for action in actions:
        print(action)
    # A refused rename (e.g. {repo_name}.md already exists) appends an ERROR:
    # action; surface that as a non-zero exit so scripts and CI can detect it.
    return 1 if any(action.startswith("ERROR:") for action in actions) else 0


def _rename_catalog(
    kb_root: Path, repo_name: str, *, dry_run: bool = False
) -> list[str]:
    """Rename index.md to {repo_name}.md and rewrite article wikilinks.

    Returns a list of human-readable action descriptions.
    """
    actions: list[str] = []
    legacy = kb_root / "index.md"
    primary = kb_root / f"{repo_name}.md"

    if not legacy.exists():
        if primary.exists():
            actions.append(f"Catalog already named {primary.name} — nothing to do.")
            return actions
        actions.append(f"No index.md found in {kb_root} — nothing to rename.")
        return actions

    if primary.exists():
        actions.append(f"ERROR: {primary.name} already exists — refusing to overwrite.")
        return actions

    # Rename catalog
    if dry_run:
        actions.append(f"[dry-run] Would rename {legacy.name} -> {primary.name}")
    else:
        legacy.rename(primary)
        actions.append(f"Renamed {legacy.name} -> {primary.name}")

    # Rewrite wikilinks in articles
    for subdir_name in ("concepts", "connections", "qa"):
        subdir = kb_root / subdir_name
        if not subdir.exists():
            continue
        for article in subdir.glob("*.md"):
            content = article.read_text(encoding="utf-8")
            new_content = rewrite_index_wikilinks(content, repo_name)
            if new_content != content:
                if dry_run:
                    actions.append(
                        f"[dry-run] Would rewrite wikilinks in {article.relative_to(kb_root)}"
                    )
                else:
                    article.write_text(new_content, encoding="utf-8")
                    actions.append(
                        f"Rewrote wikilinks in {article.relative_to(kb_root)}"
                    )

    return actions
