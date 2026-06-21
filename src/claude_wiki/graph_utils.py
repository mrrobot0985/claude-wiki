"""Shared link-graph primitives for claude-wiki."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from claude_wiki.catalog_utils import extract_tags


KB_SUBDIRS: tuple[str, ...] = ("concepts", "connections", "qa")


@dataclass(frozen=True)
class LinkGraph:
    """Single-pass index of wiki articles and their outbound wikilinks."""

    articles: dict[str, str]
    outbound: dict[str, set[str]]
    inbound: dict[str, int]
    frontmatter: dict[str, dict[str, str] | None]
    tags: dict[str, list[str]]


def build_link_graph(kb_root: Path) -> LinkGraph:
    """Read every wiki article once and index its outbound wikilinks.

    The broken-link, orphan-page, sparse-article, and frontmatter checks reuse
    this graph so the KB is read O(articles) times instead of O(articles²).
    """
    articles: dict[str, str] = {}
    outbound: dict[str, set[str]] = {}
    inbound: dict[str, int] = {}
    frontmatter: dict[str, dict[str, str] | None] = {}
    tags: dict[str, list[str]] = {}

    for article in list_articles(kb_root):
        rel = article.relative_to(kb_root).as_posix()
        content = article.read_text(encoding="utf-8")
        articles[rel] = content
        frontmatter[rel] = parse_frontmatter(content)
        tags[rel] = extract_tags(content)

        targets: set[str] = set()
        for link in extract_wikilinks(content):
            target = wikilink_target(link)
            targets.add(target)
            # A page never counts as its own inbound link.
            if target == rel.replace(".md", ""):
                continue
            if (kb_root / f"{target}.md").exists():
                inbound[target] = inbound.get(target, 0) + 1
        outbound[rel] = targets

    return LinkGraph(
        articles=articles,
        outbound=outbound,
        inbound=inbound,
        frontmatter=frontmatter,
        tags=tags,
    )


def list_articles(kb_root: Path) -> list[Path]:
    """Return all markdown articles under the KB subdirectories."""
    articles: list[Path] = []
    for subdir_name in KB_SUBDIRS:
        subdir = kb_root / subdir_name
        if subdir.exists():
            articles.extend(sorted(subdir.glob("*.md")))
    return articles


def extract_wikilinks(content: str) -> list[str]:
    """Return all [[wikilinks]] found in the content."""
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def wikilink_target(link: str) -> str:
    """Normalize a wikilink inner text to its target path.

    Strips Obsidian alias (``[[target|alias]]`` → ``target``) and anchor
    (``[[target#heading]]`` → ``target``) so link resolution and inbound
    counting compare the actual target, not the display form.
    """
    # Drop alias first (anchor may appear on either side of the pipe).
    target = link.split("|", 1)[0]
    target = target.split("#", 1)[0]
    return target.strip()


def split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split raw markdown into (frontmatter, body).

    Returns ``(None, content)`` when no YAML frontmatter delimiters are present.
    """
    if not content.startswith("---"):
        return None, content
    end = content.find("---", 3)
    if end == -1:
        return None, content
    return content[3:end].strip(), content[end + 3 :].lstrip()


def parse_frontmatter(content: str) -> dict[str, str] | None:
    """Return a simple key/value map for the YAML frontmatter block, if present.

    Only top-level scalar keys are captured; nested list items are skipped.
    A key with an empty value is still considered present.
    """
    fm, _ = split_frontmatter(content)
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
