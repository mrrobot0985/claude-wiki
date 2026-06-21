"""Lint command: kb lint [--structural-only]."""

from __future__ import annotations

import argparse
import asyncio
import fnmatch
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.config import ConfigManager
from claude_wiki.errors import RepoNotFoundError
from claude_wiki.graph_utils import (
    KB_SUBDIRS,
    LinkGraph,
    build_link_graph,
    extract_wikilinks,
    list_articles,
    split_frontmatter,
    wikilink_target,
)


SPARSE_WORD_THRESHOLD = 200

# Plain-text article path references in the catalog (e.g. ``concepts/foo``).
_CATALOG_PLAIN_REF_RE = re.compile(
    r"(?<![\w/.-])(concepts|connections|qa)/([\w/.-]+?)(?![\w/.-])"
)

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
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply safe, automatic structural fixes in place",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview what --fix would change without writing files",
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
        machine_state_dir,
        kb_root,
        daily_dir,
        repo_name=config.repo_name,
        threshold=args.threshold,
    )
    if args.fix or args.dry_run:
        issues.extend(_run_fixable_checks(kb_root))
    issues = [issue for issue in issues if not _is_ignored(issue, ignore_rules)]

    fixable_issues = [issue for issue in issues if issue.auto_fixable]
    if fixable_issues:
        if args.dry_run:
            if not args.json:
                print(f"\nDry-run: would fix {len(fixable_issues)} issue(s).")
        elif args.fix:
            _apply_fixes(kb_root, fixable_issues)
            if not args.json:
                print(f"\nFixed {len(fixable_issues)} issue(s).")
            # Re-evaluate structural checks after applying fixes so the final
            # report reflects the repaired KB.
            issues = _run_structural_checks(
                machine_state_dir,
                kb_root,
                daily_dir,
                repo_name=config.repo_name,
                threshold=args.threshold,
            )
            issues = [issue for issue in issues if not _is_ignored(issue, ignore_rules)]
            fixable_issues = []

    if not args.structural_only:
        issues.extend(_run_llm_checks(kb_root, repo_name=config.repo_name))

    today = _today_iso(config.timezone)
    report_path = _save_report(cache_dir, issues, today)
    _update_state(machine_state_dir)

    errors = sum(1 for issue in issues if issue.severity == "error")
    warnings = sum(1 for issue in issues if issue.severity == "warning")
    suggestions = sum(1 for issue in issues if issue.severity == "suggestion")

    if args.json:
        _print_lint_json(issues, include_auto_fixable=args.fix or args.dry_run)
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


def _print_lint_json(
    issues: list[_Issue], *, include_auto_fixable: bool = False
) -> None:
    """Print a machine-readable JSON payload for lint issues."""
    issue_payload: list[dict[str, Any]] = []
    for issue in issues:
        entry: dict[str, Any] = {
            "severity": issue.severity,
            "file": issue.file,
            "check": issue.check,
            "message": issue.detail,
        }
        if include_auto_fixable:
            entry["auto_fixable"] = issue.auto_fixable
        issue_payload.append(entry)
    print(json.dumps({"issues": issue_payload}, indent=2))


def _run_structural_checks(
    state_dir: Path,
    kb_root: Path,
    daily_dir: Path,
    *,
    repo_name: str | None = None,
    threshold: int = SPARSE_WORD_THRESHOLD,
) -> list[_Issue]:
    """Run all non-LLM health checks."""
    state = _load_state(state_dir)
    graph = build_link_graph(kb_root)
    issues: list[_Issue] = []
    issues.extend(_check_broken_links(kb_root, graph))
    issues.extend(_check_orphan_pages(graph))
    issues.extend(_check_orphan_sources(daily_dir, state))
    issues.extend(_check_stale_articles(daily_dir, state))
    issues.extend(_check_sparse_articles(graph, threshold=threshold))
    issues.extend(_check_frontmatter(graph))
    issues.extend(_check_single_use_tags(graph))
    issues.extend(_check_catalog_completeness(kb_root, repo_name=repo_name))
    return issues


def _run_fixable_checks(kb_root: Path) -> list[_Issue]:
    """Run structural checks whose findings can be repaired automatically."""
    issues: list[_Issue] = []
    issues.extend(_check_missing_trailing_newlines(kb_root))
    issues.extend(_check_daily_wikilinks(kb_root))
    return issues


def _check_missing_trailing_newlines(kb_root: Path) -> list[_Issue]:
    """Flag article files that do not end with a trailing newline."""
    issues: list[_Issue] = []
    for article in list_articles(kb_root):
        rel = article.relative_to(kb_root).as_posix()
        content = article.read_text(encoding="utf-8")
        if content and not content.endswith("\n"):
            issues.append(
                _Issue(
                    severity="suggestion",
                    check="missing_trailing_newline",
                    file=rel,
                    detail="Missing trailing newline",
                    auto_fixable=True,
                )
            )
    return issues


def _check_daily_wikilinks(kb_root: Path) -> list[_Issue]:
    """Flag [[daily/...]] wikilinks that should be plain text per ADR-007."""
    issues: list[_Issue] = []
    for article in list_articles(kb_root):
        rel = article.relative_to(kb_root).as_posix()
        content = article.read_text(encoding="utf-8")
        for link in extract_wikilinks(content):
            if wikilink_target(link).startswith("daily/"):
                issues.append(
                    _Issue(
                        severity="warning",
                        check="daily_wikilink",
                        file=rel,
                        detail=(
                            f"Dead daily wikilink: [[{link}]] should be plain text"
                            " per ADR-007"
                        ),
                        auto_fixable=True,
                    )
                )
    return issues


_DAILY_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def _fix_daily_links_in_content(content: str) -> str:
    """Replace [[daily/...]] wikilinks with their plain-text target path."""

    def repl(match: re.Match[str]) -> str:
        inner = match.group(1)
        if wikilink_target(inner).startswith("daily/"):
            return wikilink_target(inner)
        return match.group(0)

    return _DAILY_LINK_RE.sub(repl, content)


def _apply_fixes(kb_root: Path, fixable_issues: list[_Issue]) -> None:
    """Apply in-place repairs for safe structural issues."""
    by_file: dict[str, set[str]] = {}
    for issue in fixable_issues:
        by_file.setdefault(issue.file, set()).add(issue.check)

    for rel, checks in by_file.items():
        path = kb_root / rel
        content = path.read_text(encoding="utf-8")
        new_content = _fix_daily_links_in_content(content)
        if (
            "missing_trailing_newline" in checks
            and new_content
            and not new_content.endswith("\n")
        ):
            new_content += "\n"
        if new_content != content:
            path.write_text(new_content, encoding="utf-8")


def _check_broken_links(kb_root: Path, graph: LinkGraph) -> list[_Issue]:
    """Find wikilinks that point to non-existent articles."""
    issues: list[_Issue] = []
    for rel, content in graph.articles.items():
        for link in extract_wikilinks(content):
            target_link = wikilink_target(link)
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


def _check_orphan_pages(graph: LinkGraph) -> list[_Issue]:
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
    graph: LinkGraph, *, threshold: int = SPARSE_WORD_THRESHOLD
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


def _check_single_use_tags(graph: LinkGraph) -> list[_Issue]:
    """Flag tags that appear on exactly one article as likely typos or orphans."""
    tag_counts: dict[str, int] = {}
    tag_example: dict[str, str] = {}
    for rel, article_tags in graph.tags.items():
        for tag in article_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
            if tag not in tag_example:
                tag_example[tag] = rel

    issues: list[_Issue] = []
    for tag, count in tag_counts.items():
        if count == 1:
            issues.append(
                _Issue(
                    severity="suggestion",
                    check="tag_single_use",
                    file=tag_example[tag],
                    detail=f"Tag '{tag}' appears on only one article - possible typo or orphan tag",
                )
            )
    return issues


def _extract_catalog_references(catalog_content: str) -> set[str]:
    """Return all article paths referenced in the catalog body.

    Accepts both ``[[concepts/foo]]`` wikilinks and plain-text
    ``concepts/foo`` references, normalising anchors/aliases and stripping an
    optional ``.md`` suffix.
    """
    referenced: set[str] = set()
    for link in extract_wikilinks(catalog_content):
        referenced.add(wikilink_target(link))
    for match in _CATALOG_PLAIN_REF_RE.finditer(catalog_content):
        path = f"{match.group(1)}/{match.group(2).strip('/')}"
        if path.endswith(".md"):
            path = path[:-3]
        referenced.add(path)
    return referenced


def _check_catalog_completeness(
    kb_root: Path, repo_name: str | None = None
) -> list[_Issue]:
    """Verify the catalog references every article and every reference resolves."""
    catalog = resolve_catalog(kb_root, repo_name)
    if not catalog.exists():
        return []

    referenced = _extract_catalog_references(catalog.read_text(encoding="utf-8"))

    existing: set[str] = set()
    for article in list_articles(kb_root):
        existing.add(article.relative_to(kb_root).with_suffix("").as_posix())

    issues: list[_Issue] = []
    for path in existing:
        if path not in referenced:
            issues.append(
                _Issue(
                    severity="warning",
                    check="uncatalogued_article",
                    file=f"{path}.md",
                    detail=f"Uncatalogued article: {path}.md is not listed in the catalog",
                )
            )

    for path in referenced:
        if path not in existing:
            issues.append(
                _Issue(
                    severity="error",
                    check="stale_catalog_entry",
                    file=catalog.relative_to(kb_root).as_posix(),
                    detail=(
                        f"Stale catalog entry: catalog references {path}"
                        " but no such article exists"
                    ),
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


def _list_daily_files(daily_dir: Path) -> list[Path]:
    """Return all markdown daily logs."""
    if not daily_dir.exists():
        return []
    return sorted(daily_dir.glob("*.md"))


def _file_hash(path: Path) -> str:
    """Return a short SHA-256 hash of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def _word_count_content(content: str) -> int:
    """Return the word count of a markdown string, excluding YAML frontmatter."""
    _, body = split_frontmatter(content)
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


def _check_frontmatter(graph: LinkGraph) -> list[_Issue]:
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
    """Load the persisted compilation state.

    Tolerates a missing or corrupt state file by falling back to a fresh
    skeleton instead of raising.
    """
    state_file = state_dir / "state.json"
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {"ingested": {}}
        if isinstance(data, dict):
            return data
    return {"ingested": {}}


def _save_state(state_dir: Path, state: dict[str, Any]) -> None:
    """Persist the compilation state atomically via a sibling temp file."""
    state_dir.mkdir(parents=True, exist_ok=True)
    state_file = state_dir / "state.json"
    temp = state_file.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(temp, state_file)


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
