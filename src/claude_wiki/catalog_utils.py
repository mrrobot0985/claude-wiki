"""Shared utilities for knowledge-base catalog file resolution."""

from __future__ import annotations

import re
from pathlib import Path


def split_frontmatter(content: str) -> tuple[str | None, str]:
    """Split raw markdown into ``(frontmatter, body)``.

    Returns ``(None, content)`` when no YAML frontmatter delimiters are present.
    """
    if not content.startswith("---"):
        return None, content
    end = content.find("---", 3)
    if end == -1:
        return None, content
    return content[3:end].strip(), content[end + 3 :].lstrip()


def extract_tags(content: str) -> list[str]:
    """Extract the ``tags`` list from YAML frontmatter without importing YAML.

    Supports bracket-style lists (``tags: [a, b]`` and ``tags: ["a", "b"]``)
    and simple block lists (``tags:\n  - a\n  - b``). Missing or empty tags
    return an empty list. Duplicates within a single article are collapsed.
    """
    frontmatter, _ = split_frontmatter(content)
    if frontmatter is None:
        return []

    lines = frontmatter.splitlines()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("tags:"):
            continue

        value = stripped[len("tags:") :].strip()
        # Inline bracket list on the same line as ``tags:``.
        if value.startswith("["):
            closing = value.find("]")
            inner = value[1:closing] if closing != -1 else value[1:]
            items = []
            seen: set[str] = set()
            for raw in inner.split(","):
                item = raw.strip().strip("\"'")
                if item and item not in seen:
                    items.append(item)
                    seen.add(item)
            return items

        # Block list: collect subsequent indented ``- item`` lines.
        if not value:
            base_indent = len(line) - len(line.lstrip())
            items = []
            seen = set()
            for next_line in lines[i + 1 :]:
                if not next_line.strip():
                    continue
                next_indent = len(next_line) - len(next_line.lstrip())
                if next_indent <= base_indent:
                    break
                list_item = next_line.strip()
                if list_item.startswith("- "):
                    item = list_item[2:].strip().strip("\"'")
                    if item and item not in seen:
                        items.append(item)
                        seen.add(item)
                else:
                    break
            return items

        # Scalar value such as ``tags: single`` — treat as a one-item list.
        item = value.strip("\"'")
        if item:
            return [item]
    return []


def resolve_catalog(kb_root: Path, repo_name: str | None = None) -> Path:
    """Resolve the catalog file for a knowledge base.

    If ``repo_name`` is provided, returns ``kb_root / f"{repo_name}.md"``.
    Otherwise falls back to backward-compatible heuristics:
    - If exactly one ``{name}.md`` exists at the root (excluding ``index.md``),
      use it.
    - If ``index.md`` exists, use it.
    - Otherwise default to ``index.md``.
    """
    if repo_name is not None:
        return kb_root / f"{repo_name}.md"
    candidates = [p for p in kb_root.glob("*.md") if p.is_file()]
    named = [p for p in candidates if p.name != "index.md"]
    if len(named) == 1:
        return named[0]
    return kb_root / "index.md"


def rewrite_index_wikilinks(content: str, repo_name: str) -> str:
    """Replace ``[[index]]`` and ``[[index|alias]]`` with ``[[repo_name]]`` variants.

    Preserves ``[[index#heading]]`` as ``[[repo_name#heading]]``.
    """

    def replacer(match: re.Match[str]) -> str:
        inner = match.group(1)
        if "|" in inner:
            parts = inner.split("|", 1)
            if parts[0] == "index" or parts[0].startswith("index#"):
                new_target = parts[0].replace("index", repo_name, 1)
                return f"[[{new_target}|{parts[1]}]]"
            return match.group(0)
        if inner == "index" or inner.startswith("index#"):
            new_target = inner.replace("index", repo_name, 1)
            return f"[[{new_target}]]"
        return match.group(0)

    return re.sub(r"\[\[([^\]]+)\]\]", replacer, content)
