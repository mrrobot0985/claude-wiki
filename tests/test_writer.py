"""Tests for the sandboxed article writer (ADR-012)."""

import dataclasses
import os
from pathlib import Path

import pytest

from claude_wiki.errors import WriterError
from claude_wiki.writer import (
    CompiledArticle,
    is_valid_slug,
    resolve_article_path,
    write_article,
)


def test_valid_article_writes_to_concepts(tmp_path: Path) -> None:
    article = CompiledArticle(
        title="Test Article",
        slug="test-article",
        category="concepts",
        frontmatter='title: "Test Article"',
        body="# Test Article\n\nHello.",
    )
    path = write_article(article, tmp_path)
    assert path == tmp_path / "concepts" / "test-article.md"
    assert path.read_text(encoding="utf-8") == (
        '---\ntitle: "Test Article"\n---\n# Test Article\n\nHello.\n'
    )


@pytest.mark.parametrize("category", ["concepts", "connections", "qa"])
def test_each_category_lands_in_own_subdir(tmp_path: Path, category: str) -> None:
    article = CompiledArticle(
        title="X",
        slug="x",
        category=category,
        frontmatter="title: X",
        body="X.",
    )
    path = write_article(article, tmp_path)
    assert path == tmp_path / category / "x.md"
    assert path.exists()


def test_write_article_overwrites_existing(tmp_path: Path) -> None:
    target = tmp_path / "concepts" / "overwrite.md"
    target.parent.mkdir(parents=True)
    target.write_text("old content", encoding="utf-8")
    article = CompiledArticle(
        title="New",
        slug="overwrite",
        category="concepts",
        frontmatter="title: New",
        body="new content",
    )
    write_article(article, tmp_path)
    assert target.read_text(encoding="utf-8") == ("---\ntitle: New\n---\nnew content\n")


def test_no_temp_file_left_behind(tmp_path: Path) -> None:
    article = CompiledArticle(
        title="No Temp",
        slug="no-temp",
        category="concepts",
        frontmatter="title: No Temp",
        body="body",
    )
    write_article(article, tmp_path)
    assert not list((tmp_path / "concepts").glob(".*.tmp.*"))


def test_compiled_article_is_frozen() -> None:
    article = CompiledArticle(
        title="Frozen",
        slug="frozen",
        category="concepts",
        frontmatter="title: Frozen",
        body="body",
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        article.title = "Thawed"


@pytest.mark.parametrize(
    "title",
    ["", "   ", 123, None],
    ids=["empty", "whitespace_only", "int", "none"],
)
def test_reject_invalid_titles(title: object) -> None:
    with pytest.raises(WriterError):
        CompiledArticle(
            title=title,  # type: ignore[arg-type]
            slug="slug",
            category="concepts",
            frontmatter="title: x",
            body="body",
        )


@pytest.mark.parametrize(
    "slug",
    [
        "",
        "Foo",
        "-foo",
        "foo-",
        "foo/bar",
        "..",
        "foo..bar",
        "foo bar",
        "a" * 81,
        "\nfoo",
        "/etc/passwd",
        "foo/../bar",
    ],
)
def test_reject_invalid_slugs(slug: str) -> None:
    with pytest.raises(WriterError):
        CompiledArticle(
            title="Title",
            slug=slug,
            category="concepts",
            frontmatter="title: x",
            body="body",
        )


@pytest.mark.parametrize(
    "category",
    ["misc", "Concepts", "", "concepts/", "../concepts", 123, None],
    ids=["misc", "capitalized", "empty", "trailing_slash", "traversal", "int", "none"],
)
def test_reject_invalid_categories(category: object) -> None:
    with pytest.raises(WriterError):
        CompiledArticle(
            title="Title",
            slug="slug",
            category=category,  # type: ignore[arg-type]
            frontmatter="title: x",
            body="body",
        )


@pytest.mark.parametrize(
    "frontmatter,body",
    [
        ("", "body"),
        ("   ", "body"),
        (123, "body"),
        ("title: x", ""),
        ("title: x", "   "),
        ("title: x", 123),
    ],
    ids=[
        "empty_frontmatter",
        "whitespace_frontmatter",
        "non_str_frontmatter",
        "empty_body",
        "whitespace_body",
        "non_str_body",
    ],
)
def test_reject_invalid_frontmatter_and_body(frontmatter: object, body: object) -> None:
    with pytest.raises(WriterError):
        CompiledArticle(
            title="Title",
            slug="slug",
            category="concepts",
            frontmatter=frontmatter,  # type: ignore[arg-type]
            body=body,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "slug,expected",
    [
        ("foo", True),
        ("foo-bar", True),
        ("a", True),
        ("foo123", True),
        ("", False),
        ("Foo", False),
        ("-foo", False),
        ("foo-", False),
        ("foo/bar", False),
        ("..", False),
        ("foo..bar", False),
        ("foo bar", False),
        ("a" * 81, False),
        ("\nfoo", False),
        ("/etc/passwd", False),
        ("foo/../bar", False),
    ],
)
def test_is_valid_slug(slug: str, expected: bool) -> None:
    assert is_valid_slug(slug) is expected


def test_symlink_escape_guard_blocks_write(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    concepts_link = kb_root / "concepts"
    os.symlink(outside, concepts_link)

    article = CompiledArticle(
        title="Escape",
        slug="escape",
        category="concepts",
        frontmatter="title: Escape",
        body="body",
    )
    with pytest.raises(WriterError):
        write_article(article, kb_root)

    assert not (outside / "escape.md").exists()


def test_resolve_article_path_detects_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    kb_root = tmp_path / "kb"
    kb_root.mkdir()
    concepts_link = kb_root / "concepts"
    os.symlink(outside, concepts_link)

    article = CompiledArticle(
        title="Escape",
        slug="escape",
        category="concepts",
        frontmatter="title: Escape",
        body="body",
    )
    with pytest.raises(WriterError):
        resolve_article_path(article, kb_root)
