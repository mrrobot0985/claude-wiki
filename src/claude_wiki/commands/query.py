"""`claude-wiki query` — answer questions using the knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError
from claude_wiki.models import QueryResult


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
    handlers["query"] = _handle_query


def _handle_query(args: argparse.Namespace) -> int:
    """Run a query against the configured knowledge base."""
    detector = ConfigManager()
    try:
        repo_root = detector.find_repo_root(Path.cwd())
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    config = detector.load(repo_root)
    kb_root = detector.get_kb_root(repo_root, config)

    result = asyncio.run(
        _run_query(
            kb_root, args.question, file_back=args.file_back, repo_name=config.repo_name
        )
    )

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
        print(f"\nAnswer filed to knowledge/qa/{_slugify(args.question)}.md")

    return 0


async def _run_query(
    kb_root: Path,
    question: str,
    *,
    file_back: bool,
    repo_name: str | None = None,
    query_func: Callable[..., AsyncIterator[object]] | None = None,
) -> QueryResult:
    """Query the knowledge base and return a cited answer."""
    if _is_kb_empty(kb_root):
        return QueryResult(
            answer="No knowledge base found. Run `claude-wiki compile` first.",
            citations=[],
            confidence=0.0,
        )

    content = _read_kb_content(kb_root, repo_name)
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
    for subdir_name in ("concepts", "connections", "qa"):
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


def _read_kb_content(kb_root: Path, repo_name: str | None = None) -> str:
    """Read index + all articles into a single context string."""
    parts: list[str] = []

    index_file = resolve_catalog(kb_root, repo_name)
    if index_file.exists():
        parts.append(f"## INDEX\n\n{index_file.read_text(encoding='utf-8')}")

    for subdir_name in ("concepts", "connections", "qa"):
        subdir = kb_root / subdir_name
        if subdir.exists():
            for md_file in sorted(subdir.glob("*.md")):
                rel = md_file.relative_to(kb_root)
                content = md_file.read_text(encoding="utf-8")
                parts.append(f"## {rel}\n\n{content}")

    return "\n\n---\n\n".join(parts)


def _extract_wikilinks(text: str) -> list[str]:
    """Extract all [[wikilinks]] from markdown content."""
    return re.findall(r"\[\[([^\]]+)\]\]", text)


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug, truncated to 80 chars."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text.strip("-")[:80].rstrip("-")


def _file_back(
    kb_root: Path,
    question: str,
    result: QueryResult,
    *,
    timezone: str = "UTC",
    repo_name: str | None = None,
) -> None:
    """Create a Q&A article and update index/log."""
    qa_dir = kb_root / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)

    slug = _slugify(question) or "question"
    qa_file = qa_dir / f"{slug}.md"

    tz = ZoneInfo(timezone)
    now = datetime.now(tz)
    timestamp = now.isoformat(timespec="seconds")
    filed_date = now.strftime("%Y-%m-%d")

    title = json.dumps(f"Q: {question}")
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

    content = f"""---
title: {title}
question: {question_json}
consulted:
{consulted_lines}
filed: {filed_date}
---

# Q: {question}

## Answer

{result.answer}

## Sources Consulted

{sources_lines}

## Follow-Up Questions

- What else would you like to know?
"""

    qa_file.write_text(content, encoding="utf-8")
    _update_index(kb_root, slug, question, filed_date, repo_name)
    _append_log(kb_root, timestamp, question, result.citations, slug)


def _update_index(
    kb_root: Path,
    slug: str,
    question: str,
    filed_date: str,
    repo_name: str | None = None,
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

    index_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _append_log(
    kb_root: Path,
    timestamp: str,
    question: str,
    citations: list[str],
    slug: str,
) -> None:
    """Append a query entry to log.md."""
    log_file = kb_root / "log.md"
    if not log_file.exists():
        return

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
    log_file.write_text(log_file.read_text(encoding="utf-8") + entry, encoding="utf-8")
