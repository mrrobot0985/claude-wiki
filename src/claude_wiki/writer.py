"""Sandboxed article writer for LLM-produced KB articles (ADR-012)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from claude_wiki.errors import WriterError

CATEGORIES: tuple[str, ...] = ("concepts", "connections", "qa")
_MAX_SLUG_LEN = 80
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug)) and len(slug) <= _MAX_SLUG_LEN


def resolve_article_path(article: CompiledArticle, kb_root: Path) -> Path:
    target = kb_root / article.category / f"{article.slug}.md"
    kb_resolved = kb_root.resolve()
    target_resolved = target.resolve()
    if target_resolved != kb_resolved and kb_resolved not in target_resolved.parents:
        raise WriterError(f"article path escapes kb_root: {target}")
    return target


def write_article(article: CompiledArticle, kb_root: Path) -> Path:
    path = resolve_article_path(article, kb_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = "\n".join(["---", article.frontmatter, "---", article.body, ""])
    temp = path.parent / f".{path.name}.tmp.{os.getpid()}"
    temp.write_text(content, encoding="utf-8")
    os.replace(temp, path)
    return path


@dataclass(frozen=True)
class CompiledArticle:
    title: str
    slug: str
    category: str
    frontmatter: str
    body: str

    def __post_init__(self) -> None:
        for name in ("title", "slug", "category", "frontmatter", "body"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise WriterError(f"{name} must be a string")

        if not self.title.strip():
            raise WriterError("title must be non-empty")

        if not is_valid_slug(self.slug):
            raise WriterError(f"slug is invalid: {self.slug}")

        if self.category not in CATEGORIES:
            raise WriterError(
                f"category must be one of {CATEGORIES}, got {self.category}"
            )

        if not self.frontmatter.strip():
            raise WriterError("frontmatter must be non-empty")

        if not self.body.strip():
            raise WriterError("body must be non-empty")
