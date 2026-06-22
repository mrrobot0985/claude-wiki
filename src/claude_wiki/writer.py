"""Sandboxed article writer for LLM-produced KB articles (ADR-012)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from claude_wiki.errors import WriterError

CATEGORIES: tuple[str, ...] = ("concepts", "connections", "qa")
_MAX_SLUG_LEN = 80
# Intentionally ASCII-strict; reconcile with query._slugify in compile wiring (ADR-012).
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug)) and len(slug) <= _MAX_SLUG_LEN


def resolve_article_path(article: CompiledArticle, kb_root: Path) -> Path:
    """Return the article path confined to the resolved ``kb_root`` tree.

    Containment is realpath-based: both ``kb_root`` and the constructed target
    are resolved with ``Path.resolve()``. The target must equal ``kb_root`` or
    live inside it. ``kb_root`` may itself be a symlink (the vault is often a
    symlink to external storage); writes still land in the resolved target and
    remain confined to the resolved ``kb_root`` tree. ``..``, absolute paths,
    and category symlinks that point outside ``kb_root`` are rejected.
    """
    target = kb_root / article.category / f"{article.slug}.md"
    kb_resolved = kb_root.resolve()
    target_resolved = target.resolve()
    if target_resolved != kb_resolved and kb_resolved not in target_resolved.parents:
        raise WriterError(f"article path escapes kb_root: {target}")
    return target


def write_article(article: CompiledArticle, kb_root: Path) -> Path:
    path = resolve_article_path(article, kb_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = "\n".join(["---", article.frontmatter, "---", article.body, ""])
        temp = path.parent / f".{path.name}.tmp.{os.getpid()}"
        try:
            temp.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    except OSError as exc:
        raise WriterError(f"failed to write article {path}") from exc
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

        if any(line.strip() == "---" for line in self.frontmatter.splitlines()):
            raise WriterError("frontmatter must not contain a '---' delimiter line")

        if not self.body.strip():
            raise WriterError("body must be non-empty")
