"""Tests for claude-wiki register command (issue #68)."""

from __future__ import annotations

import json
from pathlib import Path

from claude_wiki.cli import main
from claude_wiki.global_index import GlobalIndexManager


class TestRegisterCommand:
    """Tests for register command."""

    def test_register_path_loads_lock_and_upserts_registry(self, tmp_path: Path):
        """register --path writes a registry entry with correct fields and core.md."""
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        lock = {
            "layout_version": "2",
            "repo_name": "my-project",
            "repo_owner": "local",
            "kb_dir": "project",
            "daily_dir": "daily",
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(lock))

        exit_code = main(["register", "--path", str(repo)])

        assert exit_code == 0
        entries = GlobalIndexManager().list_entries()
        assert len(entries) == 1
        entry = entries[0]
        assert entry.repo_name == "my-project"
        assert entry.repo_owner == "local"
        assert Path(entry.kb_root) == (repo / ".claude" / "knowledge").resolve(
            strict=False
        )
        assert Path(entry.repo_root) == repo.resolve()

        index = GlobalIndexManager().base_dir / "core.md"
        assert index.exists()
        text = index.read_text()
        assert "local/my-project" in text
        assert f"`{repo.resolve()}`" in text

    def test_register_path_user_mode_kb(self, tmp_path: Path):
        """register resolves user-mode kb_dir against XDG data home."""
        repo = tmp_path / "claude-wiki"
        repo.mkdir()
        (repo / ".git").mkdir()
        lock = {
            "layout_version": "2",
            "repo_name": "claude-wiki",
            "repo_owner": "mrrobot0985",
            "kb_dir": "user",
            "daily_dir": "daily",
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(lock))

        exit_code = main(["register", "--path", str(repo)])

        assert exit_code == 0
        entries = GlobalIndexManager().list_entries()
        assert len(entries) == 1
        entry = entries[0]
        expected_kb = (
            tmp_path
            / "home"
            / ".local"
            / "share"
            / "claude-wiki-vault"
            / "mrrobot0985"
            / "claude-wiki"
        ).resolve(strict=False)
        assert Path(entry.kb_root) == expected_kb
        assert entry.repo_name == "claude-wiki"
        assert entry.repo_owner == "mrrobot0985"
        assert Path(entry.repo_root) == repo.resolve()

    def test_register_missing_lock_exits_one(self, tmp_path: Path, capsys):
        """register --path on a repo without a lock exits 1."""
        repo = tmp_path / "no-lock"
        repo.mkdir()
        (repo / ".git").mkdir()

        exit_code = main(["register", "--path", str(repo)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert ".claude-wiki.lock" in captured.err
        assert GlobalIndexManager().list_entries() == []

    def test_register_corrupt_lock_exits_one(self, tmp_path: Path, capsys):
        """register --path with unparseable lock exits 1."""
        repo = tmp_path / "bad-lock"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / ".claude-wiki.lock").write_text("not json")

        exit_code = main(["register", "--path", str(repo)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert ".claude-wiki.lock" in captured.err
        assert GlobalIndexManager().list_entries() == []

    def test_register_auto_detects_repo_root_from_cwd(
        self, tmp_path: Path, monkeypatch
    ):
        """register without --path finds the lock from the current directory."""
        repo = tmp_path / "cwd-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "src").mkdir()
        lock = {
            "layout_version": "2",
            "repo_name": "cwd-project",
            "repo_owner": "local",
            "kb_dir": "project",
            "daily_dir": "daily",
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(lock))

        monkeypatch.chdir(repo / "src")
        exit_code = main(["register"])

        assert exit_code == 0
        entries = GlobalIndexManager().list_entries()
        assert len(entries) == 1
        assert entries[0].repo_name == "cwd-project"
        assert Path(entries[0].repo_root) == repo.resolve()

    def test_register_outside_repo_exits_one(self, tmp_path: Path, capsys, monkeypatch):
        """register without --path outside a git repo exits 1."""
        monkeypatch.chdir(tmp_path)
        exit_code = main(["register"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Not in a git repository" in captured.err

    def test_register_regenerates_core_md_after_registration(self, tmp_path: Path):
        """register recreates core.md after upserting the registry."""
        repo = tmp_path / "regen-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        lock = {
            "layout_version": "2",
            "repo_name": "regen-project",
            "repo_owner": "local",
            "kb_dir": "project",
            "daily_dir": "daily",
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(lock))

        # Pre-create an outdated core.md to prove it is overwritten.
        index = GlobalIndexManager().base_dir / "core.md"
        GlobalIndexManager().base_dir.mkdir(parents=True, exist_ok=True)
        index.write_text("stale content")

        exit_code = main(["register", "--path", str(repo)])

        assert exit_code == 0
        assert index.exists()
        text = index.read_text()
        assert "stale content" not in text
        assert "regen-project" in text

    def test_register_upserts_existing_entry(self, tmp_path: Path):
        """register updates kb_root and repo_root for an existing entry."""
        repo = tmp_path / "upsert-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        old_kb = tmp_path / "old-kb"
        old_kb.mkdir()
        mgr = GlobalIndexManager()
        mgr.register("upsert-project", "local", old_kb)
        first_core = (mgr.base_dir / "core.md").read_text()

        lock = {
            "layout_version": "2",
            "repo_name": "upsert-project",
            "repo_owner": "local",
            "kb_dir": "project",
            "daily_dir": "daily",
            "reports_dir": "reports",
            "timezone": "UTC",
            "compile_after_hour": 18,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(lock))

        exit_code = main(["register", "--path", str(repo)])

        assert exit_code == 0
        entries = mgr.list_entries()
        assert len(entries) == 1
        assert Path(entries[0].kb_root) == (repo / ".claude" / "knowledge").resolve(
            strict=False
        )
        assert Path(entries[0].repo_root) == repo.resolve()
        second_core = (mgr.base_dir / "core.md").read_text()
        assert second_core != first_core
