"""`claude-wiki compile` — process daily logs into the knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib
import json
import os
import re
import sys
import time

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.config import ConfigManager
from claude_wiki.errors import CompileError, WriterError
from claude_wiki.factories import DefaultConfigResolver
from claude_wiki import graph_utils
from claude_wiki.global_index import GlobalIndexManager
from claude_wiki.models import ProjectConfig
from claude_wiki.writer import (
    CATEGORIES,
    CompiledArticle,
    _ensure_confined,
    append_log,
    is_valid_slug,
    slugify,
    write_article,
    write_catalog,
)

_KB_SUBDIRS = ("concepts", "connections", "qa")

# ADR-011 compile cost-control constants (hardcoded for v1).
_CONTEXT_BUDGET_CHARS = 20_000
_PER_LOG_USD_CAP = 0.75
_TOKEN_ESTIMATE_THRESHOLD = 8_000
_CHEAP_MODEL = "claude-sonnet-4-6-20251001"

# Advisory lock around state.json RMW: bounded retries so a peer holding the
# lock cannot block this process indefinitely. The budget is larger than the
# flush/registry patterns because this lock spans LLM work, not just disk I/O.
_STATE_LOCK_RETRIES = 600
_STATE_LOCK_RETRY_INTERVAL = 1.0

_CATALOG_HEADER = (
    "# {repo_name} Knowledge Base\n\n"
    "| Article | Summary | Compiled From | Updated |\n"
    "|---|---|---|---|"
)

_DEFAULT_SCHEMA = """# Knowledge Base Schema

Return a single JSON object describing the articles to write. Do not edit files.

## Response format

```json
{
  "articles": [
    {
      "title": "Concept Name",
      "slug": "concept-name",
      "category": "concepts",
      "frontmatter": "title: \\"Concept Name\\"\\naliases: [alias]\\ntags: [tag]\\nsources:\\n  - \\"daily/YYYY-MM-DD.md\\"\\ncreated: YYYY-MM-DD\\nupdated: YYYY-MM-DD",
      "body": "# Concept Name\\n\\nCore explanation.\\n\\n## Key Points\\n\\n- Bullet point\\n\\n## Details\\n\\nDeeper explanation.\\n\\n## Related Concepts\\n\\n- [[concepts/related]] - connection note\\n\\n## Sources\\n\\n- daily/YYYY-MM-DD.md - context"
    }
  ],
  "catalog_additions": [
    {"slug": "concept-name", "category": "concepts", "summary": "one-line summary", "compiled_from": "daily/YYYY-MM-DD.md", "updated": "YYYY-MM-DD"}
  ],
  "log_created": ["concept-name"],
  "log_updated": []
}
```

## Rules

- `category` must be exactly `concepts`, `connections`, or `qa`.
- `slug` must be lowercase ASCII alphanumeric with hyphens only (max 80 chars).
- The `body` must be full replacement markdown, not an in-place edit.
- Cite the daily log as **plain text** (`- daily/YYYY-MM-DD.md - context`), never as a wikilink to a daily log — daily logs live outside the vault, so such a link is dead and collapses across repos (ADR-007).
- Use `[[concepts/slug]]` / `[[connections/slug]]` / `[[qa/slug]]` for internal wikilinks.
"""

# Safe reference format for ``log_created`` / ``log_updated``: category/slug.
_LOG_REF_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+$")


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


@contextmanager
def _state_json_lock(lock_path: Path) -> Iterator[None]:
    """Advisory lock protecting state.json read-modify-write cycles.

    Uses a non-blocking acquire with bounded retries so a peer holding the
    lock cannot block this process indefinitely; raises ``TimeoutError`` if
    the lock cannot be acquired within the retry budget.

    The retry budget is intentionally generous (10 minutes) because the lock
    spans LLM work, not just disk I/O, so a concurrent compile may need to
    wait for an in-flight compilation to finish.

    On Windows this is a no-op because ``fcntl`` is unavailable.
    """
    if sys.platform == "win32" or fcntl is None:
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        acquired = False
        for _ in range(_STATE_LOCK_RETRIES):
            try:
                fcntl.lockf(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(_STATE_LOCK_RETRY_INTERVAL)
        if not acquired:
            raise TimeoutError(f"timed out acquiring state lock at {lock_path}")
        try:
            yield
        finally:
            fcntl.lockf(lock_file.fileno(), fcntl.LOCK_UN)


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


def _median(values: list[int]) -> float:
    """Return the median of a list of integers."""
    sorted_values = sorted(values)
    n = len(sorted_values)
    if n == 0:
        return 0.0
    mid = n // 2
    if n % 2 == 1:
        return float(sorted_values[mid])
    return (sorted_values[mid - 1] + sorted_values[mid]) / 2.0


def _apply_context_budget(kb_root: Path, articles: dict[str, str]) -> dict[str, str]:
    """Trim existing articles to the context budget.

    The catalog/index is excluded from the budget. Hub articles (those with
    above-median inbound wikilinks) are kept longer than non-hubs; within each
    group, oldest articles are evicted first.
    """
    if not articles:
        return {}

    total_chars = sum(len(content) for content in articles.values())
    if total_chars <= _CONTEXT_BUDGET_CHARS:
        return articles

    # ADR-011: compute inbound counts from the already-in-memory articles dict.
    # Do not re-read the KB from disk via build_link_graph in this hot path.
    inbound: dict[str, int] = {}
    for rel_path, content in articles.items():
        for link in graph_utils.extract_wikilinks(content):
            target = graph_utils.wikilink_target(link)
            if target != rel_path.replace(".md", ""):
                inbound[target] = inbound.get(target, 0) + 1

    median_inbound = _median(list(inbound.values()))

    scored: list[tuple[str, str, bool, float]] = []
    for rel_path, content in articles.items():
        target = rel_path[: -len(".md")] if rel_path.endswith(".md") else rel_path
        count = inbound.get(target, 0)
        is_hub = count > 0 and count >= median_inbound
        path = kb_root / rel_path
        mtime = path.stat().st_mtime if path.exists() else 0.0
        scored.append((rel_path, content, is_hub, mtime))

    # Keep priority: hubs first, then newest first (larger mtime).
    scored.sort(key=lambda item: (item[2], item[3]), reverse=True)

    selected: dict[str, str] = {}
    used = 0
    for rel_path, content, _is_hub, _mtime in scored:
        if used + len(content) > _CONTEXT_BUDGET_CHARS and used > 0:
            break
        selected[rel_path] = content
        used += len(content)

    return selected


def _read_schema() -> str:
    """Read the built-in AGENTS.md schema from the package."""
    try:
        from importlib.resources import files

        return (files("claude_wiki") / "AGENTS.md").read_text(encoding="utf-8")
    except (ImportError, OSError):
        return _DEFAULT_SCHEMA


def _read_index(kb_root: Path, repo_name: str) -> str:
    """Read the current catalog, returning a default header if absent."""
    index_file = resolve_catalog(kb_root, repo_name)
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return _CATALOG_HEADER.format(repo_name=repo_name)


def _extract_json(raw_text: str) -> str:
    """Locate the outermost JSON object in ``raw_text``."""
    start = raw_text.find("{")
    if start == -1:
        raise WriterError("no JSON object found in LLM response")
    end = raw_text.rfind("}")
    if end == -1 or end < start:
        raise WriterError("unclosed JSON object in LLM response")
    return raw_text[start : end + 1]


def _parse_compile_response(
    raw_text: str,
) -> tuple[list[CompiledArticle], list[dict[str, Any]], list[str], list[str]]:
    """Parse and validate the LLM's structured response.

    Fail-fast on malformed JSON, missing fields, or any article that does not
    pass ``CompiledArticle`` validation. All articles are validated before any
    write happens (ADR-012 guardrail).
    """
    json_text = _extract_json(raw_text)
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise WriterError(f"malformed JSON in LLM response: {exc}") from exc

    if not isinstance(data, dict):
        raise WriterError("LLM response JSON must be an object")

    articles_raw = data.get("articles")
    if not isinstance(articles_raw, list):
        raise WriterError("LLM response missing 'articles' list")

    articles: list[CompiledArticle] = []
    for idx, item in enumerate(articles_raw):
        if not isinstance(item, dict):
            raise WriterError(f"article {idx} is not an object")
        slug = item.get("slug")
        if not slug:
            title = item.get("title", "")
            slug = slugify(title) if isinstance(title, str) and title.strip() else ""
        try:
            articles.append(
                CompiledArticle(
                    title=item.get("title", ""),
                    slug=slug,
                    category=item.get("category", ""),
                    frontmatter=item.get("frontmatter", ""),
                    body=item.get("body", ""),
                )
            )
        except WriterError as exc:
            raise WriterError(f"article {idx} invalid: {exc}") from exc

    catalog_additions = data.get("catalog_additions", [])
    if not isinstance(catalog_additions, list):
        raise WriterError("'catalog_additions' must be a list")
    for idx, addition in enumerate(catalog_additions):
        if not isinstance(addition, dict):
            raise WriterError(f"catalog_additions[{idx}] is not an object")
        for field_name in ("slug", "category", "summary", "compiled_from", "updated"):
            value = addition.get(field_name)
            if value is not None and not isinstance(value, str):
                raise WriterError(f"catalog_additions[{idx}] fields must be strings")
        cat = addition.get("category", "")
        slug = addition.get("slug", "")
        if cat not in CATEGORIES:
            raise WriterError(f"catalog_additions[{idx}] has invalid category: {cat}")
        if not is_valid_slug(slug):
            raise WriterError(f"catalog_additions[{idx}] has invalid slug: {slug}")

    log_created = data.get("log_created", [])
    if not isinstance(log_created, list) or not all(
        isinstance(x, str) for x in log_created
    ):
        raise WriterError("'log_created' must be a list of strings")

    log_updated = data.get("log_updated", [])
    if not isinstance(log_updated, list) or not all(
        isinstance(x, str) for x in log_updated
    ):
        raise WriterError("'log_updated' must be a list of strings")

    for ref in log_created:
        _validate_log_ref(ref)
    for ref in log_updated:
        _validate_log_ref(ref)

    return articles, catalog_additions, log_created, log_updated


def _write_articles(articles: list[CompiledArticle], kb_root: Path) -> None:
    """Write validated articles to their confined paths under ``kb_root``."""
    for article in articles:
        write_article(article, kb_root)


def _sanitize_table_field(value: Any, default: str = "") -> str:
    """Flatten a value into a single-line, pipe-free table cell."""
    text = str(value if value is not None else default)
    for char in ("|", "\n", "\r"):
        text = text.replace(char, " ")
    return text.strip()


def _format_catalog_row(
    addition: dict[str, Any], daily_filename: str, updated: str
) -> str:
    """Render one markdown table row from a catalog addition dict."""
    slug = addition.get("slug", "")
    category = addition.get("category", "")
    if not is_valid_slug(slug):
        raise WriterError(f"catalog addition has invalid slug: {slug}")
    if category not in CATEGORIES:
        raise WriterError(f"catalog addition has invalid category: {category}")
    summary = _sanitize_table_field(addition.get("summary"))
    compiled_from = _sanitize_table_field(
        addition.get("compiled_from") or f"daily/{daily_filename}"
    )
    updated = _sanitize_table_field(addition.get("updated") or updated)
    return f"| [[{category}/{slug}]] | {summary} | {compiled_from} | {updated} |"


def _update_catalog(
    kb_root: Path,
    repo_name: str,
    additions: list[dict[str, Any]],
    daily_filename: str,
    updated: str,
) -> None:
    """Merge ``catalog_additions`` into the per-repo catalog table."""
    if not additions:
        return

    catalog_path = resolve_catalog(kb_root, repo_name)
    _ensure_confined(catalog_path, kb_root)
    if catalog_path.exists():
        content = catalog_path.read_text(encoding="utf-8")
    else:
        content = _CATALOG_HEADER.format(repo_name=repo_name)

    lines = content.splitlines()
    updated_lines: list[str] = []
    replaced: set[tuple[str, str]] = set()

    for line in lines:
        matched: dict[str, Any] | None = None
        for addition in additions:
            prefix = f"| [[{addition.get('category')}/{addition.get('slug')}]] |"
            if line.startswith(prefix):
                matched = addition
                break
        if matched is not None:
            key = (matched.get("category", ""), matched.get("slug", ""))
            updated_lines.append(_format_catalog_row(matched, daily_filename, updated))
            replaced.add(key)
        else:
            updated_lines.append(line)

    for addition in additions:
        key = (addition.get("category", ""), addition.get("slug", ""))
        if key not in replaced:
            updated_lines.append(_format_catalog_row(addition, daily_filename, updated))

    write_catalog(kb_root, repo_name, "\n".join(updated_lines) + "\n")


def _validate_log_ref(ref: str) -> None:
    """Fail-fast if ``ref`` is not a safe ``category/slug`` reference."""
    if not isinstance(ref, str) or not _LOG_REF_RE.match(ref):
        raise WriterError(
            f"log_created/log_updated ref must match category/slug, got {ref!r}"
        )


def _append_compile_log(
    kb_root: Path,
    log_path: Path,
    log_created: list[str],
    log_updated: list[str],
) -> None:
    """Append a timestamped compile entry to ``kb_root/log.md``.

    ``log_created`` / ``log_updated`` refs are pre-validated in
    ``_parse_compile_response``; this function assumes they are safe.
    """
    created_refs = ", ".join(f"[[{ref}]]" for ref in log_created) or "(none)"
    updated_refs = ", ".join(f"[[{ref}]]" for ref in log_updated) or "(none)"
    entry = (
        f"## [{_iso_timestamp()}] compile | daily/{log_path.name}\n"
        f"- Source: daily/{log_path.name}\n"
        f"- Articles created: {created_refs}\n"
        f"- Articles updated: {updated_refs}\n\n"
    )
    append_log(kb_root, entry)


async def _compile_daily_log_async(
    log_path: Path,
    repo_root: Path,
    kb_root: Path,
    config: ProjectConfig,
    *,
    wiki_index: str | None = None,
    existing_articles: dict[str, str] | None = None,
    model: str | None = None,
) -> float:
    """Ask the LLM to compile a single daily log into wiki articles.

    The LLM is given only read/search tools and ``cwd=kb_root``. It returns a
    structured JSON response; Python validates the response and performs all
    writes atomically via the sandboxed writer. Returns the API cost reported
    by the agent SDK.
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
    query = claude_agent_sdk.query

    log_content = log_path.read_text(encoding="utf-8")
    schema = _read_schema()
    if wiki_index is None:
        wiki_index = _read_index(kb_root, config.repo_name)
    if existing_articles is None:
        existing_articles = _list_existing_articles(kb_root)

    # ADR-011: keep existing articles within the context budget; the catalog is
    # always included separately and never counted toward the budget.
    budgeted_articles = _apply_context_budget(kb_root, existing_articles)

    existing_context = "(No existing articles yet)"
    if budgeted_articles:
        parts = [
            f"### {rel_path}\n```markdown\n{content}\n```"
            for rel_path, content in budgeted_articles.items()
        ]
        existing_context = "\n\n".join(parts)

    prompt = f"""You are a knowledge compiler. Read the daily conversation log below and return a JSON object describing the wiki articles to create or replace.

## Schema

{schema}

## Current Wiki Catalog

{wiki_index}

## Existing Wiki Articles

{existing_context}

## Daily Log to Compile

**File:** {log_path.name}

{log_content}

## Your Task

1. Extract 3-7 key concepts and emit one article per concept in the `"articles"` array with `category: "concepts"`.
2. Emit connection articles (`category: "connections"`) when the log reveals non-obvious relationships between 2+ concepts.
3. Include rows in `"catalog_additions"` for every article you created or updated.
4. List created/updated article references in `"log_created"` / `"log_updated"`.

Return ONLY the JSON object. Do not write files — the caller writes them from your JSON response.

Every concept article must have YAML frontmatter, at least two wikilinks, 3-5 key points, and cite `daily/{log_path.name}` in its sources. Cite the daily log as **plain text** (`- daily/{log_path.name} - context`), never as a `[[wikilink]]` — daily logs live outside the vault, so a `[[daily/…]]` link is dead and collapses across repos (ADR-007).
"""

    # ADR-011: fail-fast before spending on an obviously oversized prompt.
    estimated_tokens = len(prompt) // 4
    if estimated_tokens > _TOKEN_ESTIMATE_THRESHOLD:
        raise CompileError(
            f"Prompt too large: estimated {estimated_tokens} tokens exceeds "
            f"{_TOKEN_ESTIMATE_THRESHOLD} token guard"
        )

    cost = 0.0
    response_text = ""
    options: dict[str, Any] = {
        "cwd": str(kb_root),
        "system_prompt": {"type": "preset", "preset": "claude_code"},
        "allowed_tools": ["Read", "Glob", "Grep"],
        # Read-only tools are auto-approved by ``allowed_tools``; deny any
        # other tool so the LLM cannot edit files or prompt for permissions.
        "permission_mode": "dontAsk",
        "max_turns": 30,
    }
    if model:
        options["model"] = model

    # ADR-012 fallback: chunk category-by-category here if a single response overflows.
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(**options),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                block_text = getattr(block, "text", None)
                if isinstance(block_text, str):
                    response_text += block_text
        elif isinstance(message, ResultMessage):
            cost = message.total_cost_usd or 0.0

    if not response_text.strip():
        raise WriterError("LLM returned an empty response")

    # ADR-011: per-log spend cap. Fail-fast after the call so the cost is still
    # recorded, but do not write any articles from an over-budget response.
    if cost > _PER_LOG_USD_CAP:
        raise CompileError(
            f"Compile cost ${cost:.4f} exceeds per-log cap of ${_PER_LOG_USD_CAP:.2f}",
            cost_usd=cost,
        )

    articles, catalog_additions, log_created, log_updated = _parse_compile_response(
        response_text
    )
    _write_articles(articles, kb_root)
    _update_catalog(
        kb_root, config.repo_name, catalog_additions, log_path.name, log_path.stem
    )
    _append_compile_log(kb_root, log_path, log_created, log_updated)

    return cost


def _compile_one(
    log_path: Path,
    repo_root: Path,
    kb_root: Path,
    config: ProjectConfig,
    model: str | None = None,
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
            model=model,
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
    lock_path = state_path.with_suffix(".json.lock")
    with _state_json_lock(lock_path):
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
            args.max_logs is not None
            and not args.file
            and total_pending > args.max_logs
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

        model = args.model
        if args.cheap:
            if model and model != _CHEAP_MODEL:
                print(
                    f"Warning: --cheap overrides --model; using {_CHEAP_MODEL}. "
                    "Output quality may be lower than the default model.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Warning: using cheaper model {_CHEAP_MODEL}; "
                    "output quality may be lower.",
                    file=sys.stderr,
                )
            model = _CHEAP_MODEL

        _preload_compile_context(kb_root, config.repo_name)
        total_cost = 0.0
        failed_logs: list[str] = []
        try:
            for log_path in to_compile:
                print(f"\nCompiling {log_path.name}...")
                try:
                    cost = _compile_one(
                        log_path, repo_root, kb_root, config, model=model
                    )
                except CompileError as exc:
                    print(f"  Error: {exc}", file=sys.stderr)
                    failed_logs.append(log_path.name)
                    # ADR-011: record the cost even when the log fails so the user
                    # knows what was spent and can retry or review manually.
                    if exc.cost_usd is not None:
                        state["ingested"][log_path.name] = {
                            "hash": _file_hash(log_path),
                            "compiled_at": _iso_timestamp(),
                            "cost_usd": exc.cost_usd,
                            "failed": True,
                        }
                        total_cost += exc.cost_usd
                        state["total_cost"] = (
                            state.get("total_cost", 0.0) + exc.cost_usd
                        )
                    if not args.continue_on_error:
                        break
                    continue
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
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help="Model override for the LLM compiler (default: SDK default)",
    )
    parser.add_argument(
        "--cheap",
        action="store_true",
        help=(
            f"Use the cheaper model {_CHEAP_MODEL} (opt-in; lower quality, lower cost)"
        ),
    )
    handlers["compile"] = _handle_compile
