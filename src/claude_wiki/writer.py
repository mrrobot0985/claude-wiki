"""Sandboxed article writer for LLM-produced KB articles (ADR-012)."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.errors import WriterError

CATEGORIES: tuple[str, ...] = ("concepts", "connections", "qa")
_MAX_SLUG_LEN = 80
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?$")
_SLUG_CHARS_RE = re.compile(r"[^a-z0-9-]+")


def is_valid_slug(slug: str) -> bool:
    return bool(_SLUG_RE.match(slug)) and len(slug) <= _MAX_SLUG_LEN


def slugify(text: str) -> str:
    """Convert free-form text into an ASCII-safe, writer-valid slug.

    ``is_valid_slug(slugify(x))`` is guaranteed to be ``True`` for any
    non-empty result. This is the single source of truth for slug generation
    across the package (reconciled with the legacy query helper in ADR-012).
    """
    if not isinstance(text, str):
        raise TypeError("slugify input must be a string")
    text = text.lower().strip()
    text = _SLUG_CHARS_RE.sub("-", text)
    text = re.sub(r"-+", "-", text)
    text = text.strip("-")
    text = text[:_MAX_SLUG_LEN].rstrip("-")
    return text


def _ensure_confined(target: Path, kb_root: Path) -> Path:
    """Return ``target`` after verifying it lives inside ``kb_root``.

    Containment is realpath-based. ``kb_root`` may be a symlink to external
    storage; writes still land inside the resolved ``kb_root`` tree.
    """
    kb_resolved = kb_root.resolve()
    target_resolved = target.resolve()
    if target_resolved != kb_resolved and kb_resolved not in target_resolved.parents:
        raise WriterError(f"target escapes kb_root: {target}")
    return target


def _write_atomic_confined(
    target: Path, kb_root: Path, content: str, *, label: str = "file"
) -> Path:
    """Atomically write ``content`` to ``target``, which must be inside ``kb_root``."""
    path = _ensure_confined(target, kb_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / f".{path.name}.tmp.{os.getpid()}"
        try:
            temp.write_text(content, encoding="utf-8", newline="\n")
            os.replace(temp, path)
        finally:
            temp.unlink(missing_ok=True)
    except OSError as exc:
        raise WriterError(f"failed to write {label} {path}") from exc
    return path


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
    return _ensure_confined(target, kb_root)


def write_article(article: CompiledArticle, kb_root: Path) -> Path:
    path = resolve_article_path(article, kb_root)
    content = "\n".join(["---", article.frontmatter, "---", article.body, ""])
    return _write_atomic_confined(path, kb_root, content, label="article")


def write_catalog(kb_root: Path, repo_name: str, content: str) -> Path:
    """Write the per-repo catalog markdown, confined to ``kb_root``."""
    target = resolve_catalog(kb_root, repo_name)
    return _write_atomic_confined(target, kb_root, content)


def append_log(kb_root: Path, entry: str) -> Path:
    """Append ``entry`` to ``kb_root/log.md`` atomically, creating it if needed."""
    log_path = kb_root / "log.md"
    current = (
        log_path.read_text(encoding="utf-8") if log_path.exists() else "# Build Log\n\n"
    )
    return _write_atomic_confined(log_path, kb_root, current + entry)


def apply_fix(kb_root: Path, rel_path: str, content: str) -> Path:
    """Write a lint fix to ``kb_root / rel_path`` atomically and confined.

    ``rel_path`` is resolved against ``kb_root`` and must stay inside the
    resolved ``kb_root`` tree. Symlinked articles that point outside the vault
    are rejected before any write happens.
    """
    target = kb_root / rel_path
    return _write_atomic_confined(target, kb_root, content, label="fix")


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
