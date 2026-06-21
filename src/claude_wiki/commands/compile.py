"""`claude-wiki compile` — process daily logs into the knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_wiki.config import ConfigManager
from claude_wiki.factories import DefaultConfigResolver
from claude_wiki.global_index import GlobalIndexManager
from claude_wiki.models import ProjectConfig

_KB_SUBDIRS = ("concepts", "connections", "qa")

_DEFAULT_SCHEMA = """# Knowledge Base Schema

## `knowledge/{repo_name}.md`

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

- daily/YYYY-MM-DD.md - context
```

Daily logs live outside the Obsidian vault (ADR-007), so a `daily/…` citation is
**plain text, never a `[[wikilink]]`** — a wikilink to a file outside the vault is a
dead link and, across repos, collapses to the same missing graph node.

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

# Cache populated once per ``compile`` run so the index and existing articles are
# not re-read for every daily log.
_COMPILE_CONTEXT: dict[Path, tuple[str, dict[str, str]]] = {}


def _preload_compile_context(kb_root: Path, repo_name: str) -> None:
    """Read the KB index and existing articles once per compile run."""
    _COMPILE_CONTEXT[kb_root.resolve()] = (
        _read_index(kb_root, repo_name),
        _list_existing_articles(kb_root),
    )


def _get_compile_context(kb_root: Path, repo_name: str) -> tuple[str, dict[str, str]]:
    """Return cached context, falling back to a fresh read when absent."""
    return _COMPILE_CONTEXT.get(
        kb_root.resolve(),
        (_read_index(kb_root, repo_name), _list_existing_articles(kb_root)),
    )


def _clear_compile_context(kb_root: Path) -> None:
    _COMPILE_CONTEXT.pop(kb_root.resolve(), None)


def _file_hash(path: Path) -> str:
    """Return a short SHA-256 hash of a file's contents."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _load_state(state_path: Path) -> dict[str, Any]:
    """Load compilation state or return a fresh skeleton.

    Tolerates a missing or corrupt state file (e.g. a partial write left by a
    crashed prior run) by falling back to a fresh skeleton instead of raising.
    """
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"ingested": {}, "total_cost": 0.0}
        if isinstance(data, dict):
            return data
    return {"ingested": {}, "total_cost": 0.0}


def _save_state(state_path: Path, state: dict[str, Any]) -> None:
    """Persist compilation state atomically via a sibling temp file."""
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp = state_path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temp, state_path)


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

        return (files("claude_wiki") / "AGENTS.md").read_text(encoding="utf-8")
    except (ImportError, OSError):
        return _DEFAULT_SCHEMA


def _read_index(kb_root: Path, repo_name: str) -> str:
    """Read the current index, returning a default header if absent."""
    index_file = kb_root / f"{repo_name}.md"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return (
        f"# {repo_name} Knowledge Base\n\n"
        "| Article | Summary | Compiled From | Updated |\n"
        "|---------|---------|---------------|---------|"
    )


async def _compile_daily_log_async(
    log_path: Path,
    repo_root: Path,
    kb_root: Path,
    config: ProjectConfig,
    *,
    wiki_index: str | None = None,
    existing_articles: dict[str, str] | None = None,
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
    if wiki_index is None:
        wiki_index = _read_index(kb_root, config.repo_name)
    if existing_articles is None:
        existing_articles = _list_existing_articles(kb_root)

    existing_context = "(No existing articles yet)"
    if existing_articles:
        parts = [
            f"### {rel_path}\n```markdown\n{content}\n```"
            for rel_path, content in existing_articles.items()
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
4. Update `{kb_root / f"{config.repo_name}.md"}` with a row for every new or updated article.
5. Append a timestamped entry to `{kb_root / "log.md"}`.

Every concept article must have YAML frontmatter, at least two wikilinks, 3-5 key points, and cite `daily/{log_path.name}` in its sources. Cite the daily log as **plain text** (`- daily/{log_path.name} - context`), never as a `[[wikilink]]` — daily logs live outside the vault, so a `[[daily/…]]` link is dead and collapses across repos (ADR-007).
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
    wiki_index, existing_articles = _get_compile_context(kb_root, config.repo_name)
    return asyncio.run(
        _compile_daily_log_async(
            log_path,
            repo_root,
            kb_root,
            config,
            wiki_index=wiki_index,
            existing_articles=existing_articles,
        )
    )


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
) -> tuple[list[Path], int]:
    """Determine which daily logs need compilation.

    Returns the (possibly capped) list of logs to compile and the total number
    of pending logs before any cap is applied.
    """
    if args.file:
        target = _resolve_target_file(args.file, daily_dir, repo_root)
        if target is None:
            print(f"Error: {args.file} not found", file=sys.stderr)
            return [], 0
        return [target], 1

    all_logs = _list_daily_files(daily_dir)
    if args.all:
        to_compile = all_logs
    else:
        ingested: dict[str, dict[str, Any]] = state.get("ingested", {})
        to_compile = [
            log_path
            for log_path in all_logs
            if not ingested.get(log_path.name, {}).get("hash") == _file_hash(log_path)
        ]

    total_pending = len(to_compile)
    if args.max_logs is not None and total_pending > args.max_logs:
        to_compile = to_compile[: args.max_logs]
    return to_compile, total_pending


def _handle_compile(args: argparse.Namespace) -> int:
    """Entry point for ``claude-wiki compile``."""
    detector, loader, _registrar, _migrator, _owner_resolver = (
        DefaultConfigResolver.build()
    )
    assert isinstance(detector, ConfigManager)

    start = args.path if args.path else Path.cwd()
    try:
        repo_root = detector.find_repo_root(start)
    except RuntimeError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    config = loader.load(repo_root)
    kb_root = detector.get_kb_root(repo_root, config)
    daily_dir = repo_root / config.daily_dir
    machine_state_dir = detector.get_machine_state_dir(repo_root, config)
    machine_state_dir.mkdir(parents=True, exist_ok=True)
    state_path = machine_state_dir / "state.json"
    state = _load_state(state_path)

    to_compile, total_pending = _find_files_to_compile(
        args, daily_dir, repo_root, state
    )
    if not to_compile:
        if args.file:
            return 1
        print("Nothing to compile - all daily logs are up to date.")
        return 0

    capped = (
        args.max_logs is not None and not args.file and total_pending > args.max_logs
    )

    if args.dry_run:
        if capped:
            print(
                f"[DRY RUN] Would compile {len(to_compile)} of {total_pending} pending logs "
                "(capped by --max-logs)."
            )
        print(f"[DRY RUN] Files to compile ({len(to_compile)}):")
        for log_path in to_compile:
            print(f"  - {log_path.name}")
        return 0

    if capped:
        print(
            f"Files to compile ({len(to_compile)} of {total_pending} - capped by --max-logs):"
        )
    else:
        print(f"Files to compile ({len(to_compile)}):")
    for log_path in to_compile:
        print(f"  - {log_path.name}")

    kb_root.mkdir(parents=True, exist_ok=True)
    for subdir_name in _KB_SUBDIRS:
        (kb_root / subdir_name).mkdir(parents=True, exist_ok=True)

    _preload_compile_context(kb_root, config.repo_name)
    total_cost = 0.0
    failed_logs: list[str] = []
    try:
        for log_path in to_compile:
            print(f"\nCompiling {log_path.name}...")
            try:
                cost = _compile_one(log_path, repo_root, kb_root, config)
            except Exception as exc:
                print(f"  Error: {exc}", file=sys.stderr)
                failed_logs.append(log_path.name)
                if not args.continue_on_error:
                    break
                continue

            state["ingested"][log_path.name] = {
                "hash": _file_hash(log_path),
                "compiled_at": _iso_timestamp(),
                "cost_usd": cost,
            }
            total_cost += cost
            state["total_cost"] = state.get("total_cost", 0.0) + cost
            print("  Done.")
    finally:
        _clear_compile_context(kb_root)

    _save_state(state_path, state)

    # Only stamp last_compiled when the run actually produced a usable KB.
    # Registering on a total failure would advertise a fresh compile that
    # never happened, misleading `claude-wiki status` and the global catalog.
    if not failed_logs:
        article_count = GlobalIndexManager.count_articles(kb_root)
        GlobalIndexManager().register(
            config.repo_name,
            config.repo_owner,
            kb_root,
            repo_root=repo_root,
            articles=article_count,
            last_compiled=_iso_timestamp(),
        )

    if failed_logs:
        print(
            f"\nCompilation failed for {len(failed_logs)} log(s). "
            f"Total cost: ${total_cost:.4f}",
            file=sys.stderr,
        )
    else:
        print(f"\nCompilation complete. Total cost: ${total_cost:.4f}")
        if capped:
            print(
                f"Compiled {len(to_compile)} of {total_pending} pending logs. "
                "Re-run to continue (or raise --max-logs)."
            )
    return 1 if failed_logs else 0


def _parse_max_logs(value: str) -> int:
    """Parse a positive integer for ``--max-logs``."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--max-logs must be a positive integer, got '{value}'"
        ) from exc
    if n <= 0:
        raise argparse.ArgumentTypeError(
            f"--max-logs must be a positive integer, got {n}"
        )
    return n


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
        "--continue-on-error",
        action="store_true",
        help="Keep compiling remaining logs after a failure; still exit non-zero if any failed",
    )
    parser.add_argument(
        "--max-logs",
        "--limit",
        type=_parse_max_logs,
        dest="max_logs",
        default=None,
        help="Cap the number of daily logs compiled in this run (oldest first)",
    )
    parser.add_argument(
        "--path",
        type=Path,
        help="Repo root (default: auto-detect from current directory)",
    )
    handlers["compile"] = _handle_compile
