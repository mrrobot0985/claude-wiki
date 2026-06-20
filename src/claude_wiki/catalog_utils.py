"""Shared utilities for knowledge-base catalog file resolution."""

from __future__ import annotations

import re
from pathlib import Path


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
