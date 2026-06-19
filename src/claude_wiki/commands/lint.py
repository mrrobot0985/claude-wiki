"""Lint command: kb lint [--structural-only]."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError
from claude_wiki.models import ProjectConfig


KB_SUBDIRS = ("concepts", "connections", "qa")
SPARSE_WORD_THRESHOLD = 200


@dataclass(frozen=True)
class _Issue:
    severity: str
    check: str
    file: str
    detail: str
    auto_fixable: bool = False


def register(subparsers: Any, handlers: dict[str, Any]) -> None:
    """Add the lint subcommand to the CLI."""
    parser = subparsers.add_parser(
        "lint", help="Run health checks on the knowledge base"
    )
    parser.add_argument(
        "--structural-only",
        action="store_true",
        help="Skip LLM-based contradiction checks (faster, no API cost)",
    )
    handlers["lint"] = _lint_handler


def _lint_handler(args: argparse.Namespace) -> int:
    """Execute kb lint and save a report."""
    manager = ConfigManager()
    try:
        repo_root = manager.find_repo_root(Path.cwd())
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    config = manager.load(repo_root)
    kb_root = manager.get_kb_root(repo_root, config)

    issues = _run_structural_checks(repo_root, config, kb_root)
    if not args.structural_only:
        issues.extend(_run_llm_checks(kb_root))

    today = _today_iso(config.timezone)
    report_path = _save_report(kb_root, config.reports_dir, issues, today)
    _update_state(kb_root)

    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    suggestions = sum(1 for issue in issues if issue.severity == "suggestion")

    print(f"\nResults: {errors} errors, {warnings} warnings, {suggestions} suggestions")
    print(f"Report saved to: {report_path}")

    return 1 if errors else 0


def _run_structural_checks(
    repo_root: Path, config: ProjectConfig, kb_root: Path
) -> list[_Issue]:
    """Run all non-LLM health checks."""
    state = _load_state(kb_root)
    issues: list[_Issue] = []
    issues.extend(_check_broken_links(kb_root))
    issues.extend(_check_orphan_pages(kb_root))
    issues.extend(_check_orphan_sources(repo_root, config, state))
    issues.extend(_check_stale_articles(repo_root, config, state))
    issues.extend(_check_sparse_articles(kb_root))
    return issues


def _check_broken_links(kb_root: Path) -> list[_Issue]:
    """Find wikilinks that point to non-existent articles."""
    issues: list[_Issue] = []
    for article in _list_articles(kb_root):
        content = article.read_text(encoding="utf-8")
        rel = article.relative_to(kb_root).as_posix()
        for link in _extract_wikilinks(content):
            if link.startswith("daily/"):
                continue
            target = kb_root / f"{link}.md"
            if not target.exists():
                issues.append(
                    _Issue(
                        severity="error",
                        check="broken_link",
                        file=rel,
                        detail=f"Broken link: [[{link}]] - target does not exist",
                    )
                )
    return issues


def _check_orphan_pages(kb_root: Path) -> list[_Issue]:
    """Find articles with zero inbound links."""
    issues: list[_Issue] = []
    for article in _list_articles(kb_root):
        rel = article.relative_to(kb_root).as_posix()
        link_target = rel.replace(".md", "")
        inbound = _count_inbound_links(kb_root, link_target, exclude=article)
        if inbound == 0:
            issues.append(
                _Issue(
                    severity="warning",
                    check="orphan_page",
                    file=rel,
                    detail=f"Orphan page: no other articles link to [[{link_target}]]",
                )
            )
    return issues


def _check_orphan_sources(
    repo_root: Path, config: ProjectConfig, state: dict[str, Any]
) -> list[_Issue]:
    """Find daily logs that have not been compiled yet."""
    daily_dir = repo_root / config.daily_dir
    ingested = state.get("ingested", {})
    issues: list[_Issue] = []
    for log_path in _list_daily_files(daily_dir):
        if log_path.name not in ingested:
            issues.append(
                _Issue(
                    severity="warning",
                    check="orphan_source",
                    file=f"daily/{log_path.name}",
                    detail=f"Uncompiled daily log: {log_path.name} has not been ingested",
                )
            )
    return issues


def _check_stale_articles(
    repo_root: Path, config: ProjectConfig, state: dict[str, Any]
) -> list[_Issue]:
    """Find daily logs that changed since last compilation."""
    daily_dir = repo_root / config.daily_dir
    ingested = state.get("ingested", {})
    issues: list[_Issue] = []
    for log_path in _list_daily_files(daily_dir):
        name = log_path.name
        if name in ingested:
            stored_hash = ingested[name].get("hash", "")
            current_hash = _file_hash(log_path)
            if stored_hash != current_hash:
                issues.append(
                    _Issue(
                        severity="warning",
                        check="stale_article",
                        file=f"daily/{name}",
                        detail=f"Stale: {name} has changed since last compilation",
                    )
                )
    return issues


def _check_sparse_articles(kb_root: Path) -> list[_Issue]:
    """Find articles shorter than the recommended word count."""
    issues: list[_Issue] = []
    for article in _list_articles(kb_root):
        word_count = _word_count(article)
        if word_count < SPARSE_WORD_THRESHOLD:
            rel = article.relative_to(kb_root).as_posix()
            issues.append(
                _Issue(
                    severity="suggestion",
                    check="sparse_article",
                    file=rel,
                    detail=f"Sparse article: {word_count} words (minimum recommended: {SPARSE_WORD_THRESHOLD})",
                )
            )
    return issues


def _run_llm_checks(kb_root: Path) -> list[_Issue]:
    """Run LLM-based checks, returning a system error if unavailable."""
    try:
        return asyncio.run(_check_contradictions(kb_root))
    except ImportError as exc:
        return [
            _Issue(
                severity="error",
                check="contradiction",
                file="(system)",
                detail=f"LLM check unavailable: {exc}",
            )
        ]
    except Exception as exc:  # pragma: no cover - defensive
        return [
            _Issue(
                severity="error",
                check="contradiction",
                file="(system)",
                detail=f"LLM check failed: {exc}",
            )
        ]


async def _check_contradictions(kb_root: Path) -> list[_Issue]:
    """Ask an LLM to detect contradictions across the knowledge base."""
    try:
        sdk = __import__("claude_agent_sdk")
    except ImportError as exc:
        raise ImportError(f"LLM check unavailable: {exc}") from exc

    query = sdk.query
    AssistantMessage = sdk.AssistantMessage
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    TextBlock = sdk.TextBlock

    content = _read_all_wiki_content(kb_root)
    prompt = f"""Review this knowledge base for contradictions, inconsistencies, or conflicting claims across articles.

## Knowledge Base

{content}

## Instructions

Look for:
- Direct contradictions (article A says X, article B says not-X)
- Inconsistent recommendations (different articles recommend conflicting approaches)
- Outdated information that conflicts with newer entries

For each issue found, output EXACTLY one line in this format:
CONTRADICTION: [file1] vs [file2] - description of the conflict
INCONSISTENCY: [file] - description of the inconsistency

If no issues found, output exactly: NO_ISSUES

Do NOT output anything else - no preamble, no explanation, just the formatted lines."""

    response = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            cwd=str(kb_root),
            allowed_tools=[],
            max_turns=2,
        ),
    ):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock):
                    response += block.text

    issues: list[_Issue] = []
    if "NO_ISSUES" not in response:
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("CONTRADICTION:") or line.startswith("INCONSISTENCY:"):
                issues.append(
                    _Issue(
                        severity="warning",
                        check="contradiction",
                        file="(cross-article)",
                        detail=line,
                    )
                )
    return issues


def _list_articles(kb_root: Path) -> list[Path]:
    """Return all markdown articles under the KB subdirectories."""
    articles: list[Path] = []
    for subdir_name in KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if subdir.exists():
            articles.extend(sorted(subdir.glob("*.md")))
    return articles


def _list_daily_files(daily_dir: Path) -> list[Path]:
    """Return all markdown daily logs."""
    if not daily_dir.exists():
        return []
    return sorted(daily_dir.glob("*.md"))


def _extract_wikilinks(content: str) -> list[str]:
    """Return all [[wikilinks]] found in the content."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def _count_inbound_links(
    kb_root: Path, target: str, exclude: Path | None = None
) -> int:
    """Count how many articles link to a given target."""
    count = 0
    for article in _list_articles(kb_root):
        if article == exclude:
            continue
        content = article.read_text(encoding="utf-8")
        if f"[[{target}]]" in content:
            count += 1
    return count


def _file_hash(path: Path) -> str:
    """Return a short SHA-256 hash of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _word_count(path: Path) -> int:
    """Return the word count of an article, excluding YAML frontmatter."""
    content = path.read_text(encoding="utf-8")
    if content.startswith("---"):
        end = content.find("---", 3)
        if end != -1:
            content = content[end + 3 :]
    return len(content.split())


def _read_all_wiki_content(kb_root: Path) -> str:
    """Return index + all articles as one string for LLM context."""
    parts: list[str] = []
    index_file = kb_root / "index.md"
    if index_file.exists():
        parts.append(f"## INDEX\n\n{index_file.read_text(encoding='utf-8')}")
    else:
        parts.append("## INDEX\n\n(no index)")

    for subdir_name in KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if not subdir.exists():
            continue
        for md_file in sorted(subdir.glob("*.md")):
            rel = md_file.relative_to(kb_root).as_posix()
            content = md_file.read_text(encoding="utf-8")
            parts.append(f"## {rel}\n\n{content}")

    return "\n\n---\n\n".join(parts)


def _load_state(kb_root: Path) -> dict[str, Any]:
    """Load the persisted compilation state."""
    state_file = kb_root / "state.json"
    if state_file.exists():
        return cast(dict[str, Any], json.loads(state_file.read_text(encoding="utf-8")))
    return {"ingested": {}}


def _save_state(kb_root: Path, state: dict[str, Any]) -> None:
    """Persist the compilation state."""
    state_file = kb_root / "state.json"
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _update_state(kb_root: Path) -> None:
    """Record that a lint was run."""
    state = _load_state(kb_root)
    state["last_lint"] = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")
    _save_state(kb_root, state)


def _today_iso(timezone: str = "UTC") -> str:
    """Return today's date in ISO 8601 format for the given timezone."""
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def _save_report(
    kb_root: Path, reports_dir: Path, issues: list[_Issue], today: str
) -> Path:
    """Write the markdown lint report and return its path."""
    report_dir = kb_root / reports_dir
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"lint-{today}.md"

    errors = [issue for issue in issues if issue.severity == "error"]
    warnings = [issue for issue in issues if issue.severity == "warning"]
    suggestions = [issue for issue in issues if issue.severity == "suggestion"]

    lines: list[str] = [
        f"# Lint Report - {today}",
        "",
        f"**Total issues:** {len(issues)}",
        f"- Errors: {len(errors)}",
        f"- Warnings: {len(warnings)}",
        f"- Suggestions: {len(suggestions)}",
        "",
    ]

    for severity, issue_list, marker in (
        ("Errors", errors, "x"),
        ("Warnings", warnings, "!"),
        ("Suggestions", suggestions, "?"),
    ):
        if issue_list:
            lines.append(f"## {severity}")
            lines.append("")
            for issue in issue_list:
                fixable = " (auto-fixable)" if issue.auto_fixable else ""
                lines.append(
                    f"- **[{marker}]** `{issue.file}` - {issue.detail}{fixable}"
                )
            lines.append("")

    if not issues:
        lines.append("All checks passed. Knowledge base is healthy.")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
