"""Tests for rename-catalog command."""

from __future__ import annotations

import tempfile
from pathlib import Path

from claude_wiki.catalog_utils import (
    rewrite_index_wikilinks as _rewrite_index_wikilinks,
)
from claude_wiki.commands.rename_catalog import _rename_catalog


class TestRenameCatalog:
    """Tests for the catalog rename logic."""

    def test_renames_index_and_rewrites_wikilinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "index.md").write_text("# Index")
            concepts = kb / "concepts"
            concepts.mkdir()
            (concepts / "auth.md").write_text("See [[index]] for overview.")
            connections = kb / "connections"
            connections.mkdir()
            (connections / "a.md").write_text("Link to [[index|overview]].")

            actions = _rename_catalog(kb, "my-project")

            assert "Renamed index.md -> my-project.md" in actions
            assert "Rewrote wikilinks in concepts/auth.md" in actions
            assert "Rewrote wikilinks in connections/a.md" in actions
            assert not (kb / "index.md").exists()
            assert (kb / "my-project.md").exists()
            assert "[[my-project]]" in (concepts / "auth.md").read_text()
            assert "[[my-project|overview]]" in (connections / "a.md").read_text()

    def test_dry_run_does_not_touch_disk(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "index.md").write_text("# Index")

            actions = _rename_catalog(kb, "my-project", dry_run=True)

            assert "[dry-run] Would rename index.md -> my-project.md" in actions
            assert (kb / "index.md").exists()
            assert not (kb / "my-project.md").exists()

    def test_skips_when_no_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()

            actions = _rename_catalog(kb, "my-project")

            assert "No index.md found" in actions[0]

    def test_skips_when_already_renamed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "my-project.md").write_text("# Index")

            actions = _rename_catalog(kb, "my-project")

            assert "already named my-project.md" in actions[0]

    def test_refuses_overwrite_when_primary_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "index.md").write_text("# Index")
            (kb / "my-project.md").write_text("# Other")

            actions = _rename_catalog(kb, "my-project")

            assert "ERROR: my-project.md already exists" in actions[0]

    def test_handle_returns_nonzero_on_conflict(self) -> None:
        """The CLI handler exits non-zero when a rename is refused."""
        from claude_wiki.cli import main

        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "my-project"
            kb.mkdir()
            (kb / "index.md").write_text("# Index")
            (kb / "my-project.md").write_text("# Other")

            exit_code = main(["rename-catalog", "--path", str(kb)])

            assert exit_code == 1
            assert (kb / "index.md").exists()  # nothing overwritten
            assert (kb / "my-project.md").read_text() == "# Other"

    def test_rewrites_heading_wikilinks(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "index.md").write_text("# Index")
            concepts = kb / "concepts"
            concepts.mkdir()
            (concepts / "a.md").write_text("See [[index#setup]] for details.")

            _rename_catalog(kb, "my-project")

            assert "[[my-project#setup]]" in (concepts / "a.md").read_text()


class TestRewriteIndexWikilinks:
    """Direct unit tests for the wikilink rewriter."""

    def test_simple_index_link(self) -> None:
        assert (
            _rewrite_index_wikilinks("See [[index]] here.", "repo")
            == "See [[repo]] here."
        )

    def test_aliased_index_link(self) -> None:
        assert (
            _rewrite_index_wikilinks("See [[index|overview]] here.", "repo")
            == "See [[repo|overview]] here."
        )

    def test_heading_index_link(self) -> None:
        assert (
            _rewrite_index_wikilinks("See [[index#setup]] here.", "repo")
            == "See [[repo#setup]] here."
        )

    def test_aliased_heading_index_link(self) -> None:
        assert (
            _rewrite_index_wikilinks("See [[index#setup|guide]] here.", "repo")
            == "See [[repo#setup|guide]] here."
        )

    def test_leaves_other_links_intact(self) -> None:
        text = "See [[concepts/auth]] and [[index]] here."
        assert (
            _rewrite_index_wikilinks(text, "repo")
            == "See [[concepts/auth]] and [[repo]] here."
        )
