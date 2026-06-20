"""`claude-wiki tags` — list tags indexed from the knowledge base."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

from claude_wiki.catalog_utils import extract_tags
from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError


EXIT_OK = 0
EXIT_EMPTY_KB = 1
EXIT_USAGE = 2

_EMPTY_KB_MESSAGE = "No knowledge base found. Run `claude-wiki compile` first."

_KB_SUBDIRS = ("concepts", "connections", "qa")


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    """Register the `claude-wiki tags` subcommand."""
    parser = subparsers.add_parser(
        "tags", help="List tags indexed from the knowledge base"
    )
    parser.add_argument(
        "--path",
        type=Path,
        help="Repo root (default: auto-detect from current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text",
    )
    handlers["tags"] = _handle_tags


def _is_kb_empty(kb_root: Path) -> bool:
    """Return True when no KB article subdirectories contain markdown files."""
    for subdir_name in _KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if subdir.exists() and any(subdir.glob("*.md")):
            return False
    return True


def _build_tag_index(kb_root: Path) -> dict[str, tuple[int, list[str]]]:
    """Index every tag by count and example article paths.

    Returns a mapping of ``tag -> (count, [rel_path, ...])``. Examples are
    capped at three so the human output stays concise while JSON remains
    informative.
    """
    tag_index: dict[str, tuple[int, list[str]]] = {}
    for subdir_name in _KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if not subdir.exists():
            continue
        for md_file in sorted(subdir.glob("*.md")):
            rel = md_file.relative_to(kb_root).as_posix()
            for tag in extract_tags(md_file.read_text(encoding="utf-8")):
                count, examples = tag_index.get(tag, (0, []))
                count += 1
                if len(examples) < 3:
                    examples = examples + [rel]
                tag_index[tag] = (count, examples)
    return tag_index


def _handle_tags(args: argparse.Namespace) -> int:
    """Print a tag index for the configured knowledge base."""
    detector = ConfigManager()
    start = args.path if args.path else Path.cwd()
    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return EXIT_USAGE

    config = detector.load(repo_root)
    kb_root = detector.get_kb_root(repo_root, config)

    if _is_kb_empty(kb_root):
        if args.json:
            print(json.dumps({"error": _EMPTY_KB_MESSAGE}, indent=2))
        else:
            print(_EMPTY_KB_MESSAGE)
        return EXIT_EMPTY_KB

    tag_index = _build_tag_index(kb_root)
    if not tag_index:
        message = "No tags found in the knowledge base."
        if args.json:
            print(json.dumps({"error": message}, indent=2))
        else:
            print(message)
        return EXIT_EMPTY_KB

    sorted_tags = sorted(tag_index.items(), key=lambda item: (-item[1][0], item[0]))

    if args.json:
        payload: list[dict[str, Any]] = [
            {"tag": tag, "count": count, "examples": examples}
            for tag, (count, examples) in sorted_tags
        ]
        print(json.dumps(payload, indent=2))
    else:
        labels = [tag for tag, _ in sorted_tags]
        max_len = max(len(label) for label in labels)
        for tag, (count, examples) in sorted_tags:
            pad = " " * (max_len - len(tag))
            example = examples[0] if examples else ""
            print(f"{tag}{pad}  {count}  {example}")

    return EXIT_OK
