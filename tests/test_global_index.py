"""Tests for GlobalIndexManager registry and generated core.md."""

import json
import multiprocessing
import os
import tempfile
from pathlib import Path

import pytest

from claude_wiki.global_index import GlobalIndexManager


def _register_in_process(i: int, base_str: str) -> None:
    """Helper for multiprocessing concurrency test."""
    base = Path(base_str)
    mgr = GlobalIndexManager(base_dir=base)
    (base / f"kb-{i}").mkdir(exist_ok=True)
    mgr.register(f"repo-{i}", "local", base / f"kb-{i}")


class TestGlobalIndexManager:
    """Tests for global registry operations."""

    def test_register_creates_registry_and_index(self):
        """register creates .registry.json and core.md."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb = base / "kb"
            kb.mkdir()

            mgr.register("my-project", "local", kb)

            assert (base / ".registry.json").exists()
            assert (base / "core.md").exists()
            core_text = (base / "core.md").read_text()
            assert "local/my-project" in core_text

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
        """Each generated entry links to the repo's catalog via wikilink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            kb = base / "kb"
            kb.mkdir()
            mgr = GlobalIndexManager(base_dir=base)
            mgr.register("my-repo", "owner", kb, articles=2, last_compiled="2026-06-19")

            text = (base / "core.md").read_text()
            assert "[[kb/my-repo|my-repo]]" in text
            assert "owner/my-repo" in text
            assert "**Articles:** 2" in text
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

    def test_sanitize_evicts_deleted_repo(self):
        """sanitize removes entries whose repo root no longer exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo-a"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo-a", "owner", kb, repo_root=repo)

            # Delete the repo root
            (repo / ".claude-wiki.lock").unlink()
            repo.rmdir()

            evicted = mgr.sanitize()
            assert len(evicted) == 1
            assert evicted[0].repo_name == "repo-a"
            assert mgr.list_entries() == []

    def test_sanitize_keeps_alive_repo(self):
        """sanitize preserves entries whose repo root and marker still exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo-a"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo-a", "owner", kb, repo_root=repo)

            evicted = mgr.sanitize()
            assert len(evicted) == 0
            assert len(mgr.list_entries()) == 1

    def test_sanitize_evicts_missing_marker(self):
        """sanitize removes entries whose repo exists but marker is gone."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo-a"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo-a", "owner", kb, repo_root=repo)

            # Remove marker but keep repo
            (repo / ".claude-wiki.lock").unlink()

            evicted = mgr.sanitize()
            assert len(evicted) == 1
            assert mgr.list_entries() == []

    def test_sanitize_skips_legacy_entries(self):
        """sanitize does not evict legacy entries missing repo_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb = base / "kb"
            kb.mkdir()

            mgr.register("legacy", "owner", kb)

            evicted = mgr.sanitize()
            assert len(evicted) == 0
            assert len(mgr.list_entries()) == 1

    def test_register_calls_sanitize(self):
        """register automatically triggers sanitize."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)

            alive_repo = base / "alive"
            alive_repo.mkdir()
            (alive_repo / ".claude-wiki.lock").write_text("{}")
            alive_kb = base / "alive-kb"
            alive_kb.mkdir()

            dead_repo = base / "dead"
            dead_repo.mkdir()
            (dead_repo / ".claude-wiki.lock").write_text("{}")
            dead_kb = base / "dead-kb"
            dead_kb.mkdir()

            mgr.register("dead", "owner", dead_kb, repo_root=dead_repo)
            (dead_repo / ".claude-wiki.lock").unlink()
            dead_repo.rmdir()
            dead_kb.rmdir()

            # Register a new alive repo — should trigger sanitize
            mgr.register("alive", "owner", alive_kb, repo_root=alive_repo)

            entries = mgr.list_entries()
            assert len(entries) == 1
            assert entries[0].repo_name == "alive"

    def test_partial_corruption_backup_and_preserve(self, caplog):
        """Malformed entries are skipped, good entries preserved, file backed up."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            reg = base / ".registry.json"
            reg.write_text(
                json.dumps(
                    [
                        {
                            "repo_name": "good",
                            "repo_owner": "local",
                            "kb_root": str(base / "good"),
                        },
                        {
                            "repo_name": "bad",
                            "repo_owner": "local",
                            "kb_root": str(base / "bad"),
                            "unexpected_field": 1,
                        },
                    ]
                )
            )
            mgr = GlobalIndexManager(base_dir=base)
            entries = mgr.list_entries()
            assert len(entries) == 1
            assert entries[0].repo_name == "good"
            backups = list(base.glob(".registry.json*.broken"))
            assert len(backups) == 1
            assert "bad" in caplog.text or "skipped" in caplog.text.lower()

    def test_concurrent_writes_atomic(self):
        """Concurrent registers produce valid JSON with all entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            procs = [
                multiprocessing.Process(target=_register_in_process, args=(i, tmpdir))
                for i in range(8)
            ]
            for p in procs:
                p.start()
            for p in procs:
                p.join()
            raw = (base / ".registry.json").read_text()
            data = json.loads(raw)
            assert len(data) == 8

    def test_register_rejects_non_serializable_kwargs(self):
        """Non-JSON-serializable kwargs raise ValueError before disk write."""
        import datetime

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            with pytest.raises(ValueError):
                mgr.register("x", "local", base, articles=datetime.datetime.now())
            assert not (base / ".registry.json").exists()

    def test_register_rejects_unknown_kwargs(self):
        """Unknown kwargs raise ValueError before disk write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            with pytest.raises(ValueError):
                mgr.register("x", "local", base, unknown_field=42)
            assert not (base / ".registry.json").exists()

    def test_register_converts_path_kwargs_to_strings(self):
        """Path values in known kwargs are stored as strings."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            mgr.register("x", "local", base, last_compiled=Path("2026-06-19"))
            entry = mgr.list_entries()[0]
            assert entry.last_compiled == "2026-06-19"
            assert isinstance(entry.last_compiled, str)

    def test_register_normalizes_paths_to_absolute(self, monkeypatch):
        """repo_root and kb_root are stored as absolute paths."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            monkeypatch.chdir(base)
            mgr = GlobalIndexManager(base_dir=base / "global")
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = Path("repo") / "kb"

            mgr.register("repo", "local", kb, repo_root=Path("repo"))

            entry = mgr.list_entries()[0]
            assert Path(entry.repo_root).is_absolute()
            assert Path(entry.kb_root).is_absolute()
            assert Path(entry.repo_root) == repo
            assert Path(entry.kb_root) == repo / "kb"

    def test_sanitize_preserves_legacy_relative_repo_root(self, caplog, monkeypatch):
        """Relative repo_root legacy entries are kept with a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            reg = base / ".registry.json"
            reg.write_text(
                json.dumps(
                    [
                        {
                            "repo_name": "legacy",
                            "repo_owner": "local",
                            "kb_root": str(base / "kb"),
                            "repo_root": "repo",
                        }
                    ]
                )
            )
            mgr = GlobalIndexManager(base_dir=base)
            monkeypatch.chdir("/tmp")
            evicted = mgr.sanitize()
            assert len(evicted) == 0
            assert len(mgr.list_entries()) == 1
            assert "relative" in caplog.text.lower()

    def test_sanitize_is_cwd_independent_for_absolute_repo_root(self, monkeypatch):
        """Absolute repo_root entries are not evicted by cwd changes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = base / "kb"
            kb.mkdir()
            mgr = GlobalIndexManager(base_dir=base)
            mgr.register("repo", "local", kb, repo_root=repo)

            monkeypatch.chdir("/tmp")
            evicted = mgr.sanitize()

            assert len(evicted) == 0
            assert len(mgr.list_entries()) == 1

    def test_generate_markdown_uses_wikilinks_and_plain_text(self):
        """core.md uses Obsidian wikilinks for KB indexes and plain text for directories."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert "[[kb/repo|repo]]" in text
            assert f"`{repo.resolve()}`" in text
            assert f"`{(repo / 'daily').resolve()}`" in text

    def test_core_md_links_repo_root_and_daily_dir(self):
        """core.md contains repo root and daily log paths plus wikilink to KB catalog."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "local",
                        "kb_dir": "user",
                        "daily_dir": "daily",
                    }
                )
            )
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert f"`{repo.resolve()}`" in text
            assert f"`{(repo / 'daily').resolve()}`" in text
            assert "[[kb/repo|repo]]" in text

    def test_core_md_legacy_entry_omits_repo_links(self):
        """Entries without repo_root keep only the KB wikilink."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            kb = base / "kb"
            kb.mkdir()

            mgr.register("legacy", "local", kb)
            text = (base / "core.md").read_text()
            assert "[[kb/legacy|legacy]]" in text
            assert "Repo root" not in text
            assert "Daily logs" not in text

    def test_core_md_missing_lock_defaults_daily_dir(self, caplog):
        """Missing lock file defaults daily_dir to 'daily' with a warning."""
        from claude_wiki.global_index import RegistryEntry

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            kb = base / "kb"
            kb.mkdir()

            entry = RegistryEntry(
                repo_name="repo",
                repo_owner="local",
                kb_root=str(kb),
                repo_root=str(repo),
            )
            text = mgr._generate_markdown([entry])
            assert str((repo / "daily").resolve()) in text
            assert "missing" in caplog.text.lower() or "default" in caplog.text.lower()

    def test_core_md_unparseable_lock_defaults_daily_dir(self, caplog):
        """Unparseable lock file defaults daily_dir to 'daily' with a warning."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("not json")
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert str((repo / "daily").resolve()) in text
            assert "corrupt" in caplog.text.lower() or "default" in caplog.text.lower()

    def test_core_md_relative_daily_dir_resolved(self):
        """Relative daily_dir is resolved against repo_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "local",
                        "kb_dir": "project",
                        "daily_dir": "logs/daily",
                    }
                )
            )
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert str((repo / "logs" / "daily").resolve()) in text

    def test_core_md_absolute_daily_dir_respected(self):
        """Absolute daily_dir is used as-is."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            daily = base / "external-daily"
            daily.mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "local",
                        "kb_dir": "project",
                        "daily_dir": str(daily),
                    }
                )
            )
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert str(daily.resolve()) in text

    def test_core_md_derives_kb_mode(self):
        """core.md displays the derived KB mode from the lock file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "local",
                        "kb_dir": "user",
                        "daily_dir": "daily",
                    }
                )
            )
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert "*(user KB)*" in text

    def test_core_md_custom_kb_mode(self):
        """core.md shows custom KB mode for non-mode kb_dir values."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "local",
                        "kb_dir": "custom/path",
                        "daily_dir": "daily",
                    }
                )
            )
            kb = base / "kb"
            kb.mkdir()

            mgr.register("repo", "local", kb, repo_root=repo)
            text = (base / "core.md").read_text()
            assert "*(custom KB)*" in text

    def test_core_md_generation_does_not_crash_for_missing_repo_root(self):
        """core.md generation survives a repo root that disappeared."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            mgr = GlobalIndexManager(base_dir=base)
            repo = base / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("{}")
            kb = base / "kb"
            kb.mkdir()

            # Write a registry entry directly, simulating stale state.
            reg = base / ".registry.json"
            reg.write_text(
                json.dumps(
                    [
                        {
                            "repo_name": "repo",
                            "repo_owner": "local",
                            "kb_root": str(kb),
                            "repo_root": str(repo),
                        }
                    ]
                )
            )
            (repo / ".claude-wiki.lock").unlink()
            repo.rmdir()

            # Generation should not raise even though the repo is gone.
            text = mgr._generate_markdown(mgr.list_entries())
            assert "repo" in text

    def test_empty_registry_file_returns_empty(self):
        """A registry file containing only whitespace is treated as empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / ".registry.json").write_text("   \n")
            mgr = GlobalIndexManager(base_dir=base)
            assert mgr.list_entries() == []

    def test_registry_object_not_list_returns_empty(self, caplog):
        """A registry file that parses to a non-list object is treated as empty."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            (base / ".registry.json").write_text(json.dumps({"not": "list"}))
            mgr = GlobalIndexManager(base_dir=base)
            assert mgr.list_entries() == []
            backups = list(base.glob(".registry.json*.broken"))
            assert len(backups) == 1

    def test_backup_corrupt_registry_oserror_is_swallowed(self, caplog):
        """Failure to rename a corrupt registry is logged but does not crash."""
        import json

        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            reg = base / ".registry.json"
            reg.write_text(json.dumps({"not": "list"}))
            mgr = GlobalIndexManager(base_dir=base)

            original_rename = Path.rename

            def failing_rename(self, target):
                if self == reg:
                    raise OSError("cannot rename")
                return original_rename(self, target)

            with pytest.MonkeyPatch.context() as mp:
                mp.setattr(Path, "rename", failing_rename)
                assert mgr.list_entries() == []
            assert "cannot rename" in caplog.text or "Failed to back up" in caplog.text

    def test_read_lock_non_dict_returns_none(self, caplog):
        """A lock file that parses to a non-dict type is treated as missing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text("[1, 2, 3]")
            mgr = GlobalIndexManager(base_dir=Path(tmpdir) / "global")
            assert mgr._read_lock(repo) is None
            assert "expected object" in caplog.text.lower()

    def test_resolve_path_relative_against_repo_root(self):
        """Relative paths are resolved against repo_root when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            mgr = GlobalIndexManager(base_dir=Path(tmpdir) / "global")
            resolved = mgr._resolve_path("kb", str(repo))
            assert resolved == (repo / "kb").resolve(strict=False)

    def test_resolve_path_relative_without_repo_root(self):
        """Relative paths resolve against cwd when repo_root is absent."""
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir).resolve()
                os.chdir(base)
                mgr = GlobalIndexManager(base_dir=base / "global")
                resolved = mgr._resolve_path("kb", None)
                assert resolved == (base / "kb").resolve(strict=False)
        finally:
            os.chdir(original_cwd)

    def test_format_link_escapes_spaces(self):
        """Paths containing spaces are wrapped in angle brackets."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "my dir"
            path.mkdir()
            mgr = GlobalIndexManager(base_dir=Path(tmpdir) / "global")
            link = mgr._format_link(path)
            assert link.startswith("<") and link.endswith(">")
            assert "my dir" in link

    def test_sanitize_under_lock_preserves_legacy_entries(self):
        """Entries with None or relative repo_root survive the locked sanitize pass."""
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir)
                os.chdir(base)
                mgr = GlobalIndexManager(base_dir=base)
                reg = base / ".registry.json"

                alive_repo = base / "alive"
                alive_repo.mkdir()
                (alive_repo / ".claude-wiki.lock").write_text("{}")
                # Create a directory matching the relative repo_root entry so
                # markdown generation can resolve it without error.
                (base / "repo").mkdir()

                reg.write_text(
                    json.dumps(
                        [
                            {
                                "repo_name": "alive",
                                "repo_owner": "local",
                                "kb_root": str(base / "kb1"),
                                "repo_root": str(alive_repo),
                            },
                            {
                                "repo_name": "none-root",
                                "repo_owner": "local",
                                "kb_root": str(base / "kb2"),
                            },
                            {
                                "repo_name": "relative-root",
                                "repo_owner": "local",
                                "kb_root": str(base / "kb3"),
                                "repo_root": "repo",
                            },
                        ]
                    )
                )

                # Trigger eviction so the locked re-check runs.
                (alive_repo / ".claude-wiki.lock").unlink()
                alive_repo.rmdir()

                evicted = mgr.sanitize()
                assert len(evicted) == 1
                assert evicted[0].repo_name == "alive"
                names = {e.repo_name for e in mgr.list_entries()}
                assert names == {"none-root", "relative-root"}
        finally:
            os.chdir(original_cwd)


def test_default_base_dir_isolated_from_real_home(tmp_path: Path) -> None:
    """The autouse conftest fixture must redirect XDG_DATA_HOME so a default
    GlobalIndexManager never resolves to the developer's real vault directory.

    Regression guard for the test-isolation fix (issue #42): without the
    redirect, ``GlobalIndexManager()`` writes to the live
    ``~/.local/share/claude-wiki-vault/.registry.json``.
    """
    mgr = GlobalIndexManager()
    assert mgr.base_dir.is_relative_to(tmp_path), (
        f"default base_dir {mgr.base_dir} escaped the per-test tmp area; "
        "the suite would mutate real user state"
    )
