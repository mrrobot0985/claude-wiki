"""Tests for GlobalIndexManager registry and generated index.md."""

import tempfile
from pathlib import Path

import pytest

from claude_wiki.global_index import GlobalIndexManager, RegistryEntry


class TestGlobalIndexManager:
    """Tests for global registry operations."""

    def test_register_creates_registry_and_index(self):
        """register creates .registry.json and index.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb = base / "kb"
            kb.mkdir()

            mgr.register("my-project", "local", kb)

            assert (base / ".registry.json").exists()
            assert (base / "index.md").exists()
            index_text = (base / "index.md").read_text()
            assert "local/my-project" in index_text

    def test_register_preserves_existing_fields(self):
        """register updates kb_root while preserving articles and last_compiled."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb = base / "kb"
            kb.mkdir()

            mgr.register(
                "my-project", "local", kb, articles=10, last_compiled="2026-06-18"
            )
            new_kb = base / "new-kb"
            new_kb.mkdir()
            mgr.register("my-project", "local", new_kb)

            entries = mgr.list_entries()
            assert len(entries) == 1
            assert entries[0].articles == 10
            assert entries[0].last_compiled == "2026-06-18"
            assert entries[0].kb_root == str(new_kb)

    def test_unregister_removes_entry(self):
        """unregister deletes a repo from the registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb = base / "kb"
            kb.mkdir()

            mgr.register("a", "local", kb)
            mgr.register("b", "local", kb)
            mgr.unregister("a", "local")

            entries = mgr.list_entries()
            assert len(entries) == 1
            assert entries[0].repo_name == "b"

    def test_list_entries_sorted(self):
        """Entries are sorted by owner then name."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)

            mgr.register("zebra", "alpha", base)
            mgr.register("apple", "beta", base)
            mgr.register("mango", "alpha", base)

            names = [e.repo_name for e in mgr.list_entries()]
            assert names == ["mango", "zebra", "apple"]

    def test_compact_summary_excludes_current_repo(self):
        """compact_summary omits the repo currently being queried."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)

            mgr.register("current", "local", base, articles=5)
            mgr.register("other-a", "local", base, articles=3)
            mgr.register("other-b", "local", base, articles=7)

            summary = mgr.compact_summary("current", "local")
            assert "current" not in summary
            assert "other-a(3)" in summary
            assert "other-b(7)" in summary

    def test_compact_summary_empty_when_no_others(self):
        """compact_summary returns empty string when only the current repo exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            mgr.register("solo", "local", base, articles=5)

            assert mgr.compact_summary("solo", "local") == ""

    def test_count_articles_counts_markdown_files(self):
        """count_articles sums *.md files in concepts, connections, qa."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            (kb / "concepts").mkdir(parents=True)
            (kb / "connections").mkdir(parents=True)
            (kb / "qa").mkdir(parents=True)
            (kb / "concepts" / "a.md").write_text("# A")
            (kb / "connections" / "b.md").write_text("# B")
            (kb / "qa" / "c.md").write_text("# C")
            (kb / "qa" / "d.txt").write_text("not md")

            assert GlobalIndexManager.count_articles(kb) == 3

    def test_count_articles_missing_subdirs(self):
        """count_articles handles missing subdirectories gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            (kb / "concepts").mkdir(parents=True)
            (kb / "concepts" / "a.md").write_text("# A")
            assert GlobalIndexManager.count_articles(kb) == 1

    def test_corrupted_registry_returns_empty(self):
        """A corrupted .registry.json is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / ".registry.json").write_text("not json")
            mgr = GlobalIndexManager(base_dir=base)
            assert mgr.list_entries() == []

    def test_generated_markdown_links_to_index(self):
        """Each generated line links to the repo's index.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            kb = base / "kb"
            kb.mkdir()
            mgr = GlobalIndexManager(base_dir=base)
            mgr.register("my-repo", "owner", kb, articles=2, last_compiled="2026-06-19")

            text = (base / "index.md").read_text()
            assert str(kb / "index.md") in text
            assert "owner/my-repo" in text
            assert "2 articles" in text
            assert "2026-06-19" in text

    def test_multiple_repos_in_registry(self):
        """Several repos can coexist in the global registry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb1 = base / "kb1"
            kb2 = base / "kb2"
            kb1.mkdir()
            kb2.mkdir()

            mgr.register("repo-a", "owner", kb1, articles=5)
            mgr.register("repo-b", "owner", kb2, articles=12)

            entries = mgr.list_entries()
            assert len(entries) == 2
            names = {e.repo_name for e in entries}
            assert names == {"repo-a", "repo-b"}
