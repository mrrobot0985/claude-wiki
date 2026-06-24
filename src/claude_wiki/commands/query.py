"""`claude-wiki query` — answer questions using the knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator, Callable, Iterable
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from claude_wiki.catalog_utils import extract_tags, resolve_catalog
from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError
from claude_wiki.models import QueryResult
from claude_wiki.writer import (
    CompiledArticle,
    append_log,
    slugify,
    write_article,
    write_catalog,
)


EXIT_OK = 0
EXIT_EMPTY_KB = 1
EXIT_USAGE_OR_SDK_ERROR = 2

_EMPTY_KB_MESSAGE = "No knowledge base found. Run `claude-wiki compile` first."
_EMPTY_SCOPE_MESSAGE = "No articles matched the requested scope."

_KB_SUBDIRS = ("concepts", "connections", "qa")


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    """Register the `claude-wiki query` subcommand."""
    parser = subparsers.add_parser("query", help="Query the knowledge base")
    parser.add_argument("question", help="The question to ask")
    parser.add_argument(
        "--file-back",
        action="store_true",
        help="File the answer back into the knowledge base as a Q&A article",
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
    parser.add_argument(
        "--category",
        action="append",
        choices=_KB_SUBDIRS,
        help="Restrict the query to a KB category (repeatable)",
    )
    parser.add_argument(
        "--tag",
        action="append",
        help="Restrict the query to articles tagged with NAME (repeatable; union)",
    )
    parser.add_argument(
        "--since",
        type=_parse_since,
        help="Only include articles updated/created on or after YYYY-MM-DD",
    )
    parser.add_argument(
        "--max-chars",
        type=_parse_max_chars,
        help="Cap total article content (oldest articles dropped first)",
    )
    handlers["query"] = _handle_query


def _parse_since(value: str) -> date:
    """Parse a YYYY-MM-DD date for ``--since``."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid --since date '{value}'. Expected YYYY-MM-DD."
        ) from exc


def _parse_max_chars(value: str) -> int:
    """Parse a positive integer for ``--max-chars``."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"--max-chars must be a positive integer, got '{value}'"
        ) from exc
    if n <= 0:
        raise argparse.ArgumentTypeError(
            f"--max-chars must be a positive integer, got {n}"
        )
    return n


def _handle_query(args: argparse.Namespace) -> int:
    """Run a query against the configured knowledge base."""
    detector = ConfigManager()
    start = args.path if args.path else Path.cwd()
    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return EXIT_USAGE_OR_SDK_ERROR

    config = detector.load(repo_root)
    kb_root = detector.get_kb_root(repo_root, config)

    if _is_kb_empty(kb_root):
        message = _EMPTY_KB_MESSAGE
        if args.json:
            _print_query_json(QueryResult(answer=message, citations=[]))
        else:
            print(message)
        return EXIT_EMPTY_KB

    categories: set[str] | None = set(args.category) if args.category else None
    tags: set[str] | None = set(args.tag) if args.tag else None

    try:
        result = asyncio.run(
            _run_query(
                kb_root,
                args.question,
                file_back=False,
                repo_name=config.repo_name,
                categories=categories,
                tags=tags,
                since=args.since,
                max_chars=args.max_chars,
            )
        )
    except ImportError as exc:
        message = f"Error: LLM query unavailable: {exc}"
        if args.json:
            _print_query_json(QueryResult(answer=message, citations=[]))
        else:
            print(message, file=sys.stderr)
        return EXIT_USAGE_OR_SDK_ERROR

    if result.answer in (_EMPTY_KB_MESSAGE, _EMPTY_SCOPE_MESSAGE):
        if args.json:
            _print_query_json(result)
        else:
            print(result.answer)
        return EXIT_EMPTY_KB

    if args.json:
        _print_query_json(result)
    else:
        print(result.answer)
        if result.citations:
            print("\nSources:")
            for citation in result.citations:
                print(f"- [[{citation}]]")

    if args.file_back:
        _file_back(
            kb_root,
            args.question,
            result,
            timezone=config.timezone,
            repo_name=config.repo_name,
        )
        if not args.json:
            print(f"\nAnswer filed to knowledge/qa/{_slugify(args.question)}.md")

    return EXIT_OK


def _print_query_json(result: QueryResult) -> None:
    """Print a machine-readable JSON payload for the query result.

    Confidence is omitted because the current implementation does not
    compute a meaningful confidence score; emitting 0.0 would be misleading.
    """
    payload: dict[str, Any] = {
        "answer": result.answer,
        "citations": result.citations,
    }
    print(json.dumps(payload, indent=2))


async def _run_query(
    kb_root: Path,
    question: str,
    *,
    file_back: bool,
    repo_name: str,
    categories: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    since: date | None = None,
    max_chars: int | None = None,
    query_func: Callable[..., AsyncIterator[object]] | None = None,
) -> QueryResult:
    """Query the knowledge base and return a cited answer."""
    del file_back  # handled by the CLI layer
    if _is_kb_empty(kb_root):
        return QueryResult(
            answer=_EMPTY_KB_MESSAGE,
            citations=[],
            confidence=0.0,
        )

    content, article_count = _read_kb_content(
        kb_root,
        repo_name,
        categories=categories,
        tags=tags,
        since=since,
        max_chars=max_chars,
    )
    if article_count == 0:
        return QueryResult(
            answer=_EMPTY_SCOPE_MESSAGE,
            citations=[],
            confidence=0.0,
        )

    prompt = _build_prompt(content, question)
    options: ClaudeAgentOptions | None = None

    if query_func is None:
        from claude_agent_sdk import ClaudeAgentOptions, query

        query_func = query
        options = ClaudeAgentOptions(
            cwd=str(kb_root),
            system_prompt={"type": "preset", "preset": "claude_code"},
            allowed_tools=["Read", "Glob", "Grep"],
            permission_mode="acceptEdits",
            max_turns=10,
        )

    answer = ""
    async for message in query_func(prompt=prompt, options=options):
        if hasattr(message, "content"):
            for block in message.content:
                if hasattr(block, "text"):
                    answer += block.text

    citations = _extract_wikilinks(answer)
    return QueryResult(answer=answer, citations=citations, confidence=0.0)


def _is_kb_empty(kb_root: Path) -> bool:
    """Return True if the knowledge base has no articles to consult."""
    for subdir_name in _KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if subdir.exists() and any(subdir.glob("*.md")):
            return False
    return True


def _build_prompt(content: str, question: str) -> str:
    """Build the LLM prompt with knowledge base context."""
    return f"""You are a knowledge base query engine. Answer the user's question by consulting the knowledge base below.

## How to Answer

1. Read the INDEX section first - it lists every article with a one-line summary.
2. Identify 3-10 articles that are relevant to the question.
3. Read those articles carefully (they're included below).
4. Synthesize a clear, thorough answer.
5. Cite your sources using [[wikilinks]] (e.g., [[concepts/supabase-auth]]).
6. If the knowledge base doesn't contain relevant information, say so honestly.

## Knowledge Base

{content}

## Question

{question}
"""


def _read_kb_content(
    kb_root: Path,
    repo_name: str,
    *,
    categories: Iterable[str] | None = None,
    tags: Iterable[str] | None = None,
    since: date | None = None,
    max_chars: int | None = None,
) -> tuple[str, int]:
    """Read the catalog + scoped articles into a context string.

    Returns the assembled content and the number of articles included.
    The catalog/index is always included and does not count toward the
    ``max_chars`` budget.
    """
    parts: list[str] = []

    index_file = resolve_catalog(kb_root, repo_name)
    if index_file.exists():
        parts.append(f"## INDEX\n\n{index_file.read_text(encoding='utf-8')}")

    allowed = set(categories) if categories else set(_KB_SUBDIRS)
    requested_tags = set(tags) if tags else None
    articles: list[tuple[date, str, str]] = []

    for subdir_name in _KB_SUBDIRS:
        if subdir_name not in allowed:
            continue
        subdir = kb_root / subdir_name
        if not subdir.exists():
            continue
        for md_file in sorted(subdir.glob("*.md")):
            content = md_file.read_text(encoding="utf-8")
            article_date = _article_effective_date(content)
            if since is not None and article_date is not None and article_date < since:
                continue
            if requested_tags is not None:
                article_tags = set(extract_tags(content))
                if not (article_tags & requested_tags):
                    continue
            rel = md_file.relative_to(kb_root).as_posix()
            section = f"## {rel}\n\n{content}"
            articles.append((article_date or date.min, rel, section))

    if max_chars is not None:
        articles.sort(key=lambda item: (item[0], item[1]))
        while (
            articles
            and sum(len(section) for _date, _rel, section in articles) > max_chars
        ):
            articles.pop(0)

    for _date, _rel, section in articles:
        parts.append(section)

    return "\n\n---\n\n".join(parts), len(articles)


def _article_effective_date(content: str) -> date | None:
    """Return the article's ``updated`` date, falling back to ``created``."""
    updated = _extract_frontmatter_value(content, "updated")
    if updated:
        parsed = _parse_iso_date(updated)
        if parsed is not None:
            return parsed
    created = _extract_frontmatter_value(content, "created")
    if created:
        return _parse_iso_date(created)
    return None


def _extract_frontmatter_value(content: str, key: str) -> str | None:
    """Read a single scalar value from YAML frontmatter without a parser."""
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        closing = lines.index("---", 1)
    except ValueError:
        return None

    prefix = f"{key}:"
    for line in lines[1:closing]:
        stripped = line.strip()
        if stripped.startswith(prefix):
            value = stripped[len(prefix) :].strip()
            if value.startswith(("'", '"')) and value.endswith(value[0]):
                value = value[1:-1]
            return value or None
    return None


def _parse_iso_date(value: str) -> date | None:
    """Parse a YYYY-MM-DD string, returning None on failure."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _extract_wikilinks(text: str) -> list[str]:
    """Extract all [[wikilinks]] from markdown content."""
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug, truncated to 80 chars."""
    return slugify(text)


def _file_back(
    kb_root: Path,
    question: str,
    result: QueryResult,
    *,
    timezone: str = "UTC",
    repo_name: str,
) -> None:
    """Create a Q&A article and update index/log."""
    slug = _slugify(question) or "question"

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    timestamp = now.isoformat(timespec="seconds")
    filed_date = now.strftime("%Y-%m-%d")

    title_json = json.dumps(f"Q: {question}")
    question_json = json.dumps(question)

    consulted_lines = "\n".join(f'  - "{citation}"' for citation in result.citations)
    if not consulted_lines:
        consulted_lines = '  - "none"'

    sources_lines = "\n".join(
        f"- {citation}" if citation.startswith("daily/") else f"- [[{citation}]]"
        for citation in result.citations
    )
    if not sources_lines:
        sources_lines = "- No sources available"

    frontmatter = (
        f"title: {title_json}\n"
        f"question: {question_json}\n"
        f"consulted:\n{consulted_lines}\n"
        f"filed: {filed_date}"
    )
    body = (
        f"# Q: {question}\n\n"
        f"## Answer\n\n{result.answer}\n\n"
        f"## Sources Consulted\n\n{sources_lines}\n\n"
        f"## Follow-Up Questions\n\n- What else would you like to know?"
    )

    article_title = question.strip() or "question"
    write_article(
        CompiledArticle(
            title=article_title,
            slug=slug,
            category="qa",
            frontmatter=frontmatter,
            body=body,
        ),
        kb_root,
    )
    _update_index(kb_root, slug, question, filed_date, repo_name)
    _append_log(kb_root, timestamp, question, result.citations, slug)


def _update_index(
    kb_root: Path,
    slug: str,
    question: str,
    filed_date: str,
    repo_name: str,
) -> None:
    """Add a row to the catalog for the new Q&A article."""
    index_file = resolve_catalog(kb_root, repo_name)
    if not index_file.exists():
        return

    lines = index_file.read_text(encoding="utf-8").splitlines()
    row = f"| [[qa/{slug}]] | Q&A: {question} | query | {filed_date} |"

    for i, line in enumerate(lines):
        if line.startswith("|---"):
            lines.insert(i + 1, row)
            break
    else:
        lines.append(row)

    write_catalog(kb_root, repo_name, "\n".join(lines) + "\n")


def _append_log(
    kb_root: Path,
    timestamp: str,
    question: str,
    citations: list[str],
    slug: str,
) -> None:
    """Append a query entry to log.md."""
    consulted = (
        ", ".join(
            f"{citation}" if citation.startswith("daily/") else f"[[{citation}]]"
            for citation in citations
        )
        if citations
        else "(none)"
    )
    entry = (
        f"\n## [{timestamp}] query | {question}\n"
        f"- Consulted: {consulted}\n"
        f"- Filed to: [[qa/{slug}]]\n"
    )
    append_log(kb_root, entry)
