"""Tests for the `claude-wiki tags` command."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from claude_wiki.catalog_utils import extract_tags
from claude_wiki.cli import main
from claude_wiki.commands.tags import _build_tag_index


def _article_with_tags(
    body: str,
    *,
    title: str = "Concept",
    tags: list[str] | None = None,
) -> str:
    """Return markdown with a minimal frontmatter block containing tags."""
    tag_value = "[]" if not tags else "[" + ", ".join(f'"{t}"' for t in tags) + "]"
    return (
        f"---\n"
        f'title: "{title}"\n'
        f"tags: {tag_value}\n"
        f"sources:\n"
        f'  - "daily/2026-06-18.md"\n'
        f"created: 2026-06-18\n"
        f"updated: 2026-06-18\n"
        f"---\n\n"
        f"{body}"
    )


class TestExtractTags:
    """Unit tests for the shared tag extraction helper."""

    def test_extract_tags_empty_when_no_frontmatter(self) -> None:
        """Articles without frontmatter have no tags."""
        assert extract_tags("# Just a heading\n") == []

    def test_extract_tags_empty_when_no_tags_field(self) -> None:
        """Articles with frontmatter but no tags field have no tags."""
        content = "---\ntitle: test\n---\n\n# Heading"
        assert extract_tags(content) == []

    def test_extract_tags_inline_list(self) -> None:
        """Bracket-style YAML lists are parsed."""
        content = "---\ntags: [rust, cli]\n---\n"
        assert extract_tags(content) == ["rust", "cli"]

    def test_extract_tags_quoted_inline_list(self) -> None:
        """Quoted entries in bracket lists are unwrapped."""
        content = '---\ntags: ["rust", "cli"]\n---\n'
        assert extract_tags(content) == ["rust", "cli"]

    def test_extract_tags_block_list(self) -> None:
        """Block-style YAML lists are parsed."""
        content = "---\ntags:\n  - rust\n  - cli\n---\n"
        assert extract_tags(content) == ["rust", "cli"]

    def test_extract_tags_empty_list(self) -> None:
        """An explicit empty tags list returns an empty result."""
        content = "---\ntags: []\n---\n"
        assert extract_tags(content) == []


class TestBuildTagIndex:
    """Unit tests for the tag-index builder."""

    def test_index_counts_and_collects_examples(self, tmp_path: Path) -> None:
        """The index counts occurrences and records example paths."""
        kb = tmp_path / "kb"
        concepts = kb / "concepts"
        concepts.mkdir(parents=True)
        (concepts / "rust.md").write_text(
            _article_with_tags("Rust body", tags=["rust", "cli"])
        )
        (concepts / "cli.md").write_text(_article_with_tags("CLI body", tags=["cli"]))

        index = _build_tag_index(kb)
        assert index["rust"] == (1, ["concepts/rust.md"])
        assert index["cli"] == (2, ["concepts/cli.md", "concepts/rust.md"])

    def test_index_scans_all_subdirs(self, tmp_path: Path) -> None:
        """Tags are gathered from concepts, connections, and qa."""
        kb = tmp_path / "kb"
        (kb / "concepts").mkdir(parents=True)
        (kb / "connections").mkdir(parents=True)
        (kb / "qa").mkdir(parents=True)
        (kb / "concepts" / "rust.md").write_text(
            _article_with_tags("Rust body", tags=["rust"])
        )
        (kb / "connections" / "rust-cli.md").write_text(
            _article_with_tags("Connection body", tags=["rust"])
        )
        (kb / "qa" / "question.md").write_text(
            _article_with_tags("Answer body", tags=["rust"])
        )

        index = _build_tag_index(kb)
        assert index["rust"] == (
            3,
            ["concepts/rust.md", "connections/rust-cli.md", "qa/question.md"],
        )

    def test_index_empty_kb(self, tmp_path: Path) -> None:
        """An empty KB yields an empty tag index."""
        kb = tmp_path / "kb"
        kb.mkdir()
        assert _build_tag_index(kb) == {}


class TestTagsCommand:
    """CLI-level tests for `claude-wiki tags`."""

    def _repo_and_kb(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = repo / ".claude" / "knowledge"
        kb_root.mkdir(parents=True)
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "layout_version": "2",
                    "repo_name": "repo",
                    "repo_owner": "local",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        return repo, kb_root

    def test_tags_lists_counts_and_examples(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Human output shows each tag, its count, and an example article."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "rust.md").write_text(
            _article_with_tags(long_text, tags=["rust", "cli"])
        )
        (concepts / "cli.md").write_text(_article_with_tags(long_text, tags=["cli"]))

        monkeypatch.chdir(repo)

        exit_code = main(["tags"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "rust" in captured.out
        assert "cli" in captured.out
        assert "concepts/rust.md" in captured.out

    def test_tags_empty_kb_exits_one(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An empty KB prints a message and exits non-zero."""
        repo, _kb_root = self._repo_and_kb(tmp_path)

        monkeypatch.chdir(repo)

        exit_code = main(["tags"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "No knowledge base found" in captured.out

    def test_tags_no_articles_exits_one(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A KB with no articles in concepts/connections/qa exits 1."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        (kb_root / "repo.md").write_text("# Index")

        monkeypatch.chdir(repo)

        exit_code = main(["tags"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "No knowledge base found" in captured.out

    def test_tags_json_output(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--json emits a machine-readable list of tag records."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "rust.md").write_text(_article_with_tags(long_text, tags=["rust"]))

        monkeypatch.chdir(repo)

        exit_code = main(["tags", "--json"])
        captured = capsys.readouterr()

        assert exit_code == 0
        payload = json.loads(captured.out)
        rust = next(item for item in payload if item["tag"] == "rust")
        assert rust["count"] == 1
        assert "concepts/rust.md" in rust["examples"]

    def test_tags_path_flag_resolves_repo_from_outside(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--path` targets a repo without `cd`-ing into it (issue #44)."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        (concepts / "rust.md").write_text(_article_with_tags("body", tags=["rust"]))

        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        exit_code = main(["tags", "--path", str(repo)])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "rust" in captured.out

    def test_tags_outside_repo_exits_two(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Running tags outside any repo prints an error and exits 2."""
        monkeypatch.chdir(tmp_path)

        exit_code = main(["tags"])
        captured = capsys.readouterr()

        assert exit_code == 2
        assert "Not in a git repository" in captured.err
