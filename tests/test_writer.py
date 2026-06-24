"""Tests for the sandboxed article writer (ADR-012)."""

import dataclasses
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_wiki.errors import WriterError
from claude_wiki.writer import (
    CompiledArticle,
    apply_fix,
    append_log,
    is_valid_slug,
    resolve_article_path,
    slugify,
    write_article,
    write_catalog,
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


def test_temp_file_cleaned_up_when_replace_fails(tmp_path: Path) -> None:
    article = CompiledArticle(
        title="Temp Leak",
        slug="temp-leak",
        category="concepts",
        frontmatter="title: Temp Leak",
        body="body",
    )
    with patch("claude_wiki.writer.os.replace", side_effect=OSError("boom")):
        with pytest.raises(WriterError):
            write_article(article, tmp_path)

    assert not list((tmp_path / "concepts").glob(".*.tmp.*"))


@pytest.mark.parametrize(
    "frontmatter",
    [
        "title: x\n---\nmalicious: y",
        "---\ntitle: x",
        "title: x\n---",
    ],
)
def test_reject_frontmatter_containing_delimiter(frontmatter: str) -> None:
    with pytest.raises(
        WriterError, match="frontmatter must not contain a '---' delimiter line"
    ):
        CompiledArticle(
            title="Title",
            slug="slug",
            category="concepts",
            frontmatter=frontmatter,
            body="body",
        )


def test_write_article_wraps_oserror_as_writer_error(tmp_path: Path) -> None:
    article = CompiledArticle(
        title="Blocked",
        slug="blocked",
        category="concepts",
        frontmatter="title: Blocked",
        body="body",
    )
    tmp_path.chmod(0o555)
    try:
        with pytest.raises(WriterError) as exc_info:
            write_article(article, tmp_path)
        assert isinstance(exc_info.value.__cause__, OSError)
        assert "failed to write article" in str(exc_info.value)
    finally:
        tmp_path.chmod(0o755)


def test_symlinked_kb_root_writes_to_resolved_target(tmp_path: Path) -> None:
    real_vault = tmp_path / "real_vault"
    real_vault.mkdir()
    kb_link = tmp_path / "kb"
    os.symlink(real_vault, kb_link)

    article = CompiledArticle(
        title="Symlinked",
        slug="symlinked",
        category="concepts",
        frontmatter="title: Symlinked",
        body="body",
    )
    path = write_article(article, kb_link)

    real_path = real_vault / "concepts" / "symlinked.md"
    assert path.resolve() == real_path
    assert real_path.exists()
    assert real_path.read_text(encoding="utf-8") == "---\ntitle: Symlinked\n---\nbody\n"


def test_escape_blocked_when_kb_root_is_symlink(tmp_path: Path) -> None:
    real_vault = tmp_path / "real_vault"
    real_vault.mkdir()
    kb_link = tmp_path / "kb"
    os.symlink(real_vault, kb_link)

    outside = tmp_path / "outside"
    outside.mkdir()
    concepts_link = real_vault / "concepts"
    os.symlink(outside, concepts_link)

    article = CompiledArticle(
        title="Escape",
        slug="escape",
        category="concepts",
        frontmatter="title: Escape",
        body="body",
    )
    with pytest.raises(WriterError):
        write_article(article, kb_link)

    assert not (outside / "escape.md").exists()


def test_body_starting_with_three_dashes_is_allowed(tmp_path: Path) -> None:
    article = CompiledArticle(
        title="Body Dash",
        slug="body-dash",
        category="concepts",
        frontmatter='title: "Body Dash"',
        body="---\n# section",
    )
    path = write_article(article, tmp_path)
    assert path.read_text(encoding="utf-8") == (
        '---\ntitle: "Body Dash"\n---\n---\n# section\n'
    )


@pytest.mark.parametrize(
    "text",
    [
        "Simple Title",
        "  Spaced Out  ",
        "a-b-c",
        "With_Underscores",
        "Multi---Hyphens",
        " leading-",
        "-trailing ",
        "Unicode: café, 日本語",
        "a " * 100,
    ],
)
def test_slugify_produces_valid_slugs_or_empty(text: str) -> None:
    result = slugify(text)
    if result:
        assert is_valid_slug(result)


def test_slugify_matches_query_behavior_for_ascii() -> None:
    """ASCII inputs stay identical to the old query._slugify implementation."""
    from claude_wiki.commands.query import _slugify as query_slugify

    ascii_inputs = [
        "How do I handle auth?",
        "simple title",
        "with_underscores and spaces",
        "a-b-c",
        " leading-",
        "-trailing ",
        "Multi---Hyphens",
    ]
    for text in ascii_inputs:
        assert slugify(text) == query_slugify(text)


def test_write_catalog_confined_to_kb_root(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    path = write_catalog(kb, "my-repo", "# My Catalog\n")
    assert path == kb / "my-repo.md"
    assert path.read_text(encoding="utf-8") == "# My Catalog\n"


def test_append_log_creates_and_appends_confined_to_kb_root(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    append_log(kb, "## Entry one\n")
    append_log(kb, "## Entry two\n")
    log_path = kb / "log.md"
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "## Entry one" in content
    assert "## Entry two" in content


def test_apply_fix_writes_relative_path(tmp_path: Path) -> None:
    kb = tmp_path / "kb"
    kb.mkdir()
    path = apply_fix(kb, "concepts/note.md", "# Note\n")
    assert path == kb / "concepts" / "note.md"
    assert path.read_text(encoding="utf-8") == "# Note\n"


def test_apply_fix_blocked_by_symlinked_article(tmp_path: Path) -> None:
    """A symlinked article pointing outside kb_root must not be fixed."""
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_file = outside / "stolen.md"
    outside_file.write_text("# Stolen\n")
    kb = tmp_path / "kb"
    kb.mkdir()
    concepts = kb / "concepts"
    concepts.mkdir()
    os.symlink(outside_file, concepts / "stolen.md")

    with pytest.raises(WriterError):
        apply_fix(kb, "concepts/stolen.md", "# Replaced\n")

    assert outside_file.read_text(encoding="utf-8") == "# Stolen\n"


def test_symlinked_catalog_blocked_from_escape(tmp_path: Path) -> None:
    """A catalog file symlinked outside kb_root must not be written."""
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_catalog = outside / "stolen.md"
    outside_catalog.write_text("# Stolen\n")
    kb = tmp_path / "kb"
    kb.mkdir()
    os.symlink(outside_catalog, kb / "my-repo.md")

    with pytest.raises(WriterError):
        write_catalog(kb, "my-repo", "# My Catalog\n")

    assert outside_catalog.read_text(encoding="utf-8") == "# Stolen\n"


def test_symlinked_log_blocked_from_escape(tmp_path: Path) -> None:
    """A log.md symlinked outside kb_root must not be appended."""
    outside = tmp_path / "outside"
    outside.mkdir()
    outside_log = outside / "stolen.md"
    outside_log.write_text("# Stolen Log\n")
    kb = tmp_path / "kb"
    kb.mkdir()
    os.symlink(outside_log, kb / "log.md")

    with pytest.raises(WriterError):
        append_log(kb, "## Entry\n")

    assert "## Entry" not in outside_log.read_text(encoding="utf-8")
