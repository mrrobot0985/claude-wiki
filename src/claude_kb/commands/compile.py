"""`kb compile` — process daily logs into the knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from claude_kb.config import ConfigManager
from claude_kb.factories import DefaultConfigResolver
from claude_kb.global_index import GlobalIndexManager
from claude_kb.models import ProjectConfig

_KB_SUBDIRS = ("concepts", "connections", "qa")

_DEFAULT_SCHEMA = """# Knowledge Base Schema

## `knowledge/index.md`

Master catalog table:

| Article | Summary | Compiled From | Updated |
|---------|---------|---------------|---------|
| [[concepts/example]] | One-line summary | daily/YYYY-MM-DD.md | YYYY-MM-DD |

## Concept articles (`knowledge/concepts/`)

```markdown
---
title: "Concept Name"
aliases: [alias]
tags: [tag]
sources:
  - "daily/YYYY-MM-DD.md"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Concept Name

Core explanation.

## Key Points

- Bullet point

## Details

Deeper explanation.

## Related Concepts

- [[concepts/related]] - connection note

## Sources

- [[daily/YYYY-MM-DD.md]] - context
```

## Connection articles (`knowledge/connections/`)

Link two or more concepts and explain the non-obvious relationship.

## Build log (`knowledge/log.md`)

```markdown
## [YYYY-MM-DDTHH:MM:SS] compile | daily/YYYY-MM-DD.md
- Source: daily/YYYY-MM-DD.md
- Articles created: [[concepts/x]]
- Articles updated: (none)
```
"""


def _file_hash(path: Path) -> str:
    """Return a short SHA-256 hash of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_state(state_path: Path) -> dict[str, Any]:
    """Load compilation state or return a fresh skeleton."""
    if state_path.exists():
        return cast(dict[str, Any], json.loads(state_path.read_text(encoding="utf-8")))
    return {"ingested": {}, "total_cost": 0.0}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    """Persist compilation state atomically."""
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _iso_timestamp() -> str:
    """Current local time in ISO-8601 format."""
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _list_daily_files(daily_dir: Path) -> list[Path]:
    """Return sorted daily log files."""
    if not daily_dir.exists():
        return []
    return sorted(daily_dir.glob("*.md"))


def _list_existing_articles(kb_root: Path) -> dict[str, str]:
    """Read all compiled wiki articles for LLM context."""
    articles: dict[str, str] = {}
    for subdir_name in _KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if not subdir.exists():
            continue
        for article in sorted(subdir.glob("*.md")):
            rel = article.relative_to(kb_root)
            articles[str(rel)] = article.read_text(encoding="utf-8")
    return articles


def _read_schema() -> str:
    """Read the built-in AGENTS.md schema from the package."""
    try:
        from importlib.resources import files

        return (files("claude_kb") / "AGENTS.md").read_text(encoding="utf-8")
    except (ImportError, OSError):
        return _DEFAULT_SCHEMA


def _read_index(kb_root: Path) -> str:
    """Read the current index, returning a default header if absent."""
    index_file = kb_root / "index.md"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return (
        "# Knowledge Base Index\n\n"
        "| Article | Summary | Compiled From | Updated |\n"
        "|---------|---------|---------------|---------|"
    )


async def _compile_daily_log_async(
    log_path: Path,
    repo_root: Path,
    kb_root: Path,
    config: ProjectConfig,
) -> float:
    """Ask the LLM to compile a single daily log into wiki articles.

    The LLM is granted file-editing tools and writes articles directly into
    ``kb_root``. Returns the API cost reported by the agent SDK.
    """
    try:
        claude_agent_sdk = importlib.import_module("claude_agent_sdk")
    except ImportError as exc:  # pragma: no cover - runtime dependency issue
        raise RuntimeError(
            "claude-agent-sdk is required for compilation. "
            "Install it with the 'dev' optional group (uv pip install -e . --group dev)."
        ) from exc

    AssistantMessage = claude_agent_sdk.AssistantMessage
    ClaudeAgentOptions = claude_agent_sdk.ClaudeAgentOptions
    ResultMessage = claude_agent_sdk.ResultMessage
    TextBlock = claude_agent_sdk.TextBlock
    query = claude_agent_sdk.query

    log_content = log_path.read_text(encoding="utf-8")
    schema = _read_schema()
    wiki_index = _read_index(kb_root)
    existing = _list_existing_articles(kb_root)

    existing_context = "(No existing articles yet)"
    if existing:
        parts = [
            f"### {rel_path}\n```markdown\n{content}\n```"
            for rel_path, content in existing.items()
        ]
        existing_context = "\n\n".join(parts)

    prompt = f"""You are a knowledge compiler. Read the daily conversation log below and extract structured wiki articles.

## Schema

{schema}

## Current Wiki Index

{wiki_index}

## Existing Wiki Articles

{existing_context}

## Daily Log to Compile

**File:** {log_path.name}

{log_content}

## Your Task

1. Extract 3-7 key concepts and create one article per concept in `{kb_root / "concepts"}`.
2. Create connection articles in `{kb_root / "connections"}` when the log reveals non-obvious relationships between 2+ concepts.
3. Update existing articles if the log adds new information.
4. Update `{kb_root / "index.md"}` with a row for every new or updated article.
5. Append a timestamped entry to `{kb_root / "log.md"}`.

Every concept article must have YAML frontmatter, at least two wikilinks, 3-5 key points, and cite `daily/{log_path.name}` in its sources.
"""

    cost = 0.0
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(repo_root),
            system_prompt={"type": "preset", "preset": "claude_code"},
            allowed_tools=["Read", "Write", "Edit", "Glob", "Grep"],
            permission_mode="acceptEdits",
            max_turns=30,
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    continue
        elif isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0

    return cost


def _compile_one(
    log_path: Path,
    repo_root: Path,
    kb_root: Path,
    config: ProjectConfig,
) -> float:
    """Synchronous wrapper around the async LLM compiler call."""
    return asyncio.run(_compile_daily_log_async(log_path, repo_root, kb_root, config))


def _resolve_target_file(
    file_arg: str, daily_dir: Path, repo_root: Path
) -> Path | None:
    """Resolve a --file argument to an existing daily log path."""
    target = Path(file_arg)
    if not target.is_absolute():
        candidate = daily_dir / target.name
        if candidate.exists():
            return candidate
        candidate = repo_root / file_arg
        if candidate.exists():
            return candidate
    elif target.exists():
        return target
    return None


def _find_files_to_compile(
    args: argparse.Namespace,
    daily_dir: Path,
    repo_root: Path,
    state: dict[str, Any],
) -> list[Path]:
    """Determine which daily logs need compilation."""
    if args.file:
        target = _resolve_target_file(args.file, daily_dir, repo_root)
        if target is None:
            print(f"Error: {args.file} not found", file=sys.stderr)
            return []
        return [target]

    all_logs = _list_daily_files(daily_dir)
    if args.all:
        return all_logs

    ingested: dict[str, dict[str, Any]] = state.get("ingested", {})
    to_compile: list[Path] = []
    for log_path in all_logs:
        prev = ingested.get(log_path.name, {})
        if not prev or prev.get("hash") != _file_hash(log_path):
            to_compile.append(log_path)
    return to_compile


def _handle_compile(args: argparse.Namespace) -> int:
    """Entry point for ``kb compile``."""
    detector, loader, _registrar, _migrator = DefaultConfigResolver.build()
    assert isinstance(detector, ConfigManager)

    start = args.path if args.path else Path.cwd()
    try:
        repo_root = detector.find_repo_root(start)
    except RuntimeError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    config = loader.load(repo_root)
    kb_root = detector.get_kb_root(config)
    daily_dir = repo_root / config.daily_dir
    state_path = kb_root / "state.json"
    state = _load_state(state_path)

    to_compile = _find_files_to_compile(args, daily_dir, repo_root, state)
    if not to_compile:
        if args.file:
            return 1
        print("Nothing to compile - all daily logs are up to date.")
        return 0

    prefix = "[DRY RUN] " if args.dry_run else ""
    print(f"{prefix}Files to compile ({len(to_compile)}):")
    for log_path in to_compile:
        print(f"  - {log_path.name}")

    if args.dry_run:
        return 0

    kb_root.mkdir(parents=True, exist_ok=True)
    for subdir_name in _KB_SUBDIRS:
        (kb_root / subdir_name).mkdir(parents=True, exist_ok=True)

    total_cost = 0.0
    for log_path in to_compile:
        print(f"\nCompiling {log_path.name}...")
        try:
            cost = _compile_one(log_path, repo_root, kb_root, config)
        except Exception as exc:
            print(f"  Error: {exc}", file=sys.stderr)
            continue

        state["ingested"][log_path.name] = {
            "hash": _file_hash(log_path),
            "compiled_at": _iso_timestamp(),
            "cost_usd": cost,
        }
        total_cost += cost
        state["total_cost"] = state.get("total_cost", 0.0) + cost
        print("  Done.")

    _save_state(state_path, state)

    article_count = GlobalIndexManager.count_articles(kb_root)
    GlobalIndexManager().register(
        config.repo_name,
        config.repo_owner,
        kb_root,
        articles=article_count,
        last_compiled=_iso_timestamp(),
    )

    print(f"\nCompilation complete. Total cost: ${total_cost:.4f}")
    return 0


def register(
    subparsers: Any,
    handlers: dict[str, Any],
) -> None:
    """Register the ``compile`` subcommand."""
    parser = subparsers.add_parser(
        "compile",
        help="Compile daily logs into the knowledge base",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Force recompile all daily logs",
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Compile a specific daily log file (e.g. daily/2026-06-19.md)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which logs would be compiled without running the compiler",
    )
    parser.add_argument(
        "--path",
        type=Path,
        help="Repo root (default: auto-detect from current directory)",
    )
    handlers["compile"] = _handle_compile
