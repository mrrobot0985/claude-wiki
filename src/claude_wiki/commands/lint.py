"""Lint command: kb lint [--structural-only]."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from zoneinfo import ZoneInfo

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError


KB_SUBDIRS = ("concepts", "connections", "qa")
SPARSE_WORD_THRESHOLD = 200

EXIT_OK = 0
EXIT_WARNINGS = 1
EXIT_ERRORS = 2
EXIT_USAGE = 2


@dataclass(frozen=True)
class _Issue:
    severity: str
    check: str
    file: str
    detail: str
    auto_fixable: bool = False


@dataclass(frozen=True)
class _IgnoreRule:
    path_pattern: str
    check: str
    reason: str


@dataclass(frozen=True)
class _LinkGraph:
    """Single-pass index of wiki articles and their outbound wikilinks."""

    articles: dict[str, str]
    outbound: dict[str, set[str]]
    inbound: dict[str, int]
    frontmatter: dict[str, dict[str, str] | None]


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
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        help="Exit with status 1 when only warnings are present",
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
        "--threshold",
        type=int,
        default=SPARSE_WORD_THRESHOLD,
        help=f"Sparse-article word threshold (default: {SPARSE_WORD_THRESHOLD})",
    )
    handlers["lint"] = _lint_handler


def _lint_handler(args: argparse.Namespace) -> int:
    """Execute kb lint and save a report."""
    manager = ConfigManager()
    start = args.path if args.path else Path.cwd()
    try:
        repo_root = manager.find_repo_root(start)
    except RepoNotFoundError:
        print("Error: Not in a git repository.", file=sys.stderr)
        return EXIT_USAGE

    config = manager.load(repo_root)
    kb_root = manager.get_kb_root(repo_root, config)
    machine_state_dir = manager.get_machine_state_dir(repo_root, config)
    cache_dir = manager.get_cache_dir(repo_root, config)

    daily_dir = repo_root / config.daily_dir
    ignore_rules = _load_ignore_rules(repo_root)
    issues = _run_structural_checks(
        machine_state_dir, kb_root, daily_dir, threshold=args.threshold
    )
    if not args.structural_only:
        issues.extend(_run_llm_checks(kb_root, repo_name=config.repo_name))
    issues = [issue for issue in issues if not _is_ignored(issue, ignore_rules)]

    today = _today_iso(config.timezone)
    report_path = _save_report(cache_dir, issues, today)
    _update_state(machine_state_dir)

    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    suggestions = sum(1 for issue in issues if issue.severity == "suggestion")

    if args.json:
        _print_lint_json(issues)
    else:
        print(
            f"\nResults: {errors} errors, {warnings} warnings, {suggestions} suggestions"
        )
        print(f"Report saved to: {report_path}")

    if errors:
        return EXIT_ERRORS
    if warnings and args.fail_on_warning:
        return EXIT_WARNINGS
    return EXIT_OK


def _print_lint_json(issues: list[_Issue]) -> None:
    """Print a machine-readable JSON payload for lint issues."""
    payload: dict[str, Any] = {
        "issues": [
            {
                "severity": issue.severity,
                "file": issue.file,
                "check": issue.check,
                "message": issue.detail,
            }
            for issue in issues
        ]
    }
    print(json.dumps(payload, indent=2))


def _build_link_graph(kb_root: Path) -> _LinkGraph:
    """Read every wiki article once and index its outbound wikilinks.

    The broken-link, orphan-page, sparse-article, and frontmatter checks reuse
    this graph so the KB is read O(articles) times instead of O(articles²).
    """
    articles: dict[str, str] = {}
    outbound: dict[str, set[str]] = {}
    inbound: dict[str, int] = {}
    frontmatter: dict[str, dict[str, str] | None] = {}

    for article in _list_articles(kb_root):
        rel = article.relative_to(kb_root).as_posix()
        content = article.read_text(encoding="utf-8")
        articles[rel] = content
        frontmatter[rel] = _parse_frontmatter(content)

        targets: set[str] = set()
        for link in _extract_wikilinks(content):
            target = _wikilink_target(link)
            targets.add(target)
            # A page never counts as its own inbound link.
            if target == rel.replace(".md", ""):
                continue
            if (kb_root / f"{target}.md").exists():
                inbound[target] = inbound.get(target, 0) + 1
        outbound[rel] = targets

    return _LinkGraph(
        articles=articles, outbound=outbound, inbound=inbound, frontmatter=frontmatter
    )


def _run_structural_checks(
    state_dir: Path,
    kb_root: Path,
    daily_dir: Path,
    *,
    threshold: int = SPARSE_WORD_THRESHOLD,
) -> list[_Issue]:
    """Run all non-LLM health checks."""
    state = _load_state(state_dir)
    graph = _build_link_graph(kb_root)
    issues: list[_Issue] = []
    issues.extend(_check_broken_links(kb_root, graph))
    issues.extend(_check_orphan_pages(graph))
    issues.extend(_check_orphan_sources(daily_dir, state))
    issues.extend(_check_stale_articles(daily_dir, state))
    issues.extend(_check_sparse_articles(graph, threshold=threshold))
    issues.extend(_check_frontmatter(graph))
    return issues


def _check_broken_links(kb_root: Path, graph: _LinkGraph) -> list[_Issue]:
    """Find wikilinks that point to non-existent articles."""
    issues: list[_Issue] = []
    for rel, content in graph.articles.items():
        for link in _extract_wikilinks(content):
            target_link = _wikilink_target(link)
            if target_link.startswith("daily/"):
                continue
            target = kb_root / f"{target_link}.md"
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


def _check_orphan_pages(graph: _LinkGraph) -> list[_Issue]:
    """Find articles with zero inbound links."""
    issues: list[_Issue] = []
    for rel in graph.articles:
        link_target = rel.replace(".md", "")
        if graph.inbound.get(link_target, 0) == 0:
            issues.append(
                _Issue(
                    severity="warning",
                    check="orphan_page",
                    file=rel,
                    detail=f"Orphan page: no other articles link to [[{link_target}]]",
                )
            )
    return issues


def _check_orphan_sources(daily_dir: Path, state: dict[str, Any]) -> list[_Issue]:
    """Find daily logs that have not been compiled yet."""
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


def _check_stale_articles(daily_dir: Path, state: dict[str, Any]) -> list[_Issue]:
    """Find daily logs that changed since last compilation."""
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


def _check_sparse_articles(
    graph: _LinkGraph, *, threshold: int = SPARSE_WORD_THRESHOLD
) -> list[_Issue]:
    """Find articles shorter than the recommended word count."""
    issues: list[_Issue] = []
    for rel, content in graph.articles.items():
        word_count = _word_count_content(content)
        if word_count < threshold:
            issues.append(
                _Issue(
                    severity="suggestion",
                    check="sparse_article",
                    file=rel,
                    detail=f"Sparse article: {word_count} words (minimum recommended: {threshold})",
                )
            )
    return issues


def _run_llm_checks(kb_root: Path, repo_name: str | None = None) -> list[_Issue]:
    """Run LLM-based checks, returning a system error if unavailable."""
    try:
        return asyncio.run(_check_contradictions(kb_root, repo_name))
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


async def _check_contradictions(
    kb_root: Path, repo_name: str | None = None
) -> list[_Issue]:
    """Ask an LLM to detect contradictions across the knowledge base."""
    try:
        sdk = __import__("claude_agent_sdk")
    except ImportError as exc:
        raise ImportError(f"LLM check unavailable: {exc}") from exc

    query = sdk.query
    AssistantMessage = sdk.AssistantMessage
    ClaudeAgentOptions = sdk.ClaudeAgentOptions
    TextBlock = sdk.TextBlock

    content = _read_all_wiki_content(kb_root, repo_name)
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


def _wikilink_target(link: str) -> str:
    """Normalize a wikilink inner text to its target path.

    Strips Obsidian alias (``[[target|alias]]`` → ``target``) and anchor
    (``[[target#heading]]`` → ``target``) so link resolution and inbound
    counting compare the actual target, not the display form.
    """
    # Drop alias first (anchor may appear on either side of the pipe).
    target = link.split("|", 1)[0]
    target = target.split("#", 1)[0]
    return target.strip()


def _file_hash(path: Path) -> str:
    """Return a short SHA-256 hash of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split raw markdown into (frontmatter, body).

    Returns ``(None, content)`` when no YAML frontmatter delimiters are present.
    """
    if not content.startswith("---"):
        return None, content
    end = content.find("---", 3)
    if end == -1:
        return None, content
    return content[3:end].strip(), content[end + 3 :].lstrip()


def _parse_frontmatter(content: str) -> dict[str, str] | None:
    """Return a simple key/value map for the YAML frontmatter block, if present.

    Only top-level scalar keys are captured; nested list items are skipped.
    A key with an empty value is still considered present.
    """
    fm, _ = _split_frontmatter(content)
    if fm is None:
        return None
    result: dict[str, str] = {}
    for line in fm.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        result[key.strip()] = value.strip()
    return result


def _word_count_content(content: str) -> int:
    """Return the word count of a markdown string, excluding YAML frontmatter."""
    _, body = _split_frontmatter(content)
    return len(body.split())


def _word_count(path: Path) -> int:
    """Return the word count of an article, excluding YAML frontmatter."""
    return _word_count_content(path.read_text(encoding="utf-8"))


# Required frontmatter fields per article type. title and sources are errors;
# the rest are warnings.
_CONCEPT_REQUIRED_FIELDS = (
    ("title", "error"),
    ("sources", "error"),
    ("aliases", "warning"),
    ("tags", "warning"),
    ("created", "warning"),
    ("updated", "warning"),
)
_ARTICLE_REQUIRED_FIELDS = (
    ("title", "error"),
    ("sources", "error"),
    ("created", "warning"),
    ("updated", "warning"),
)


def _check_frontmatter(graph: _LinkGraph) -> list[_Issue]:
    """Enforce required YAML frontmatter fields in KB article subdirs."""
    issues: list[_Issue] = []
    for rel, frontmatter in graph.frontmatter.items():
        subdir_name = rel.split("/", 1)[0]
        if subdir_name not in KB_SUBDIRS:
            continue
        required = (
            _CONCEPT_REQUIRED_FIELDS
            if subdir_name == "concepts"
            else _ARTICLE_REQUIRED_FIELDS
        )
        if frontmatter is None:
            # Articles without frontmatter are flagged for every required field.
            for field, severity in required:
                issues.append(
                    _Issue(
                        severity=severity,
                        check=f"frontmatter_missing_{field}",
                        file=rel,
                        detail=f"Missing frontmatter field: {field}",
                    )
                )
            continue
        for field, severity in required:
            if field not in frontmatter:
                issues.append(
                    _Issue(
                        severity=severity,
                        check=f"frontmatter_missing_{field}",
                        file=rel,
                        detail=f"Missing frontmatter field: {field}",
                    )
                )
    return issues


def _load_ignore_rules(repo_root: Path) -> list[_IgnoreRule]:
    """Load ``.claude-wiki-lint-ignore`` from the repo root.

    Format: ``path::check::reason`` where path is relative to the KB root.
    Lines starting with ``#`` and blank lines are skipped.
    """
    ignore_file = repo_root / ".claude-wiki-lint-ignore"
    if not ignore_file.exists():
        return []
    rules: list[_IgnoreRule] = []
    for line in ignore_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split("::", 2)
        if len(parts) != 3:
            continue
        rules.append(
            _IgnoreRule(path_pattern=parts[0], check=parts[1], reason=parts[2])
        )
    return rules


def _is_ignored(issue: _Issue, rules: list[_IgnoreRule]) -> bool:
    """Return True when an issue matches an ignore rule."""
    for rule in rules:
        if rule.check != issue.check:
            continue
        if fnmatch.fnmatch(issue.file, rule.path_pattern):
            return True
    return False


def _read_all_wiki_content(kb_root: Path, repo_name: str | None = None) -> str:
    """Return index + all articles as one string for LLM context."""
    parts: list[str] = []
    index_file = resolve_catalog(kb_root, repo_name)
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


def _load_state(state_dir: Path) -> dict[str, Any]:
    """Load the persisted compilation state."""
    state_file = state_dir / "state.json"
    if state_file.exists():
        return cast(dict[str, Any], json.loads(state_file.read_text(encoding="utf-8")))
    return {"ingested": {}}


def _save_state(state_dir: Path, state: dict[str, Any]) -> None:
    """Persist the compilation state."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _update_state(state_dir: Path) -> None:
    """Record that a lint was run."""
    state = _load_state(state_dir)
    state["last_lint"] = datetime.now(ZoneInfo("UTC")).isoformat(timespec="seconds")
    _save_state(state_dir, state)


def _today_iso(timezone: str = "UTC") -> str:
    """Return today's date in ISO 8601 format for the given timezone."""
    try:
        tz = ZoneInfo(timezone)
    except Exception:
        tz = ZoneInfo("UTC")
    return datetime.now(tz).date().isoformat()


def _save_report(cache_dir: Path, issues: list[_Issue], today: str) -> Path:
    """Write the markdown lint report and return its path."""
    report_dir = cache_dir / "reports"
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
