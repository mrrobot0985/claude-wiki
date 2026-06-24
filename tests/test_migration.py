"""Tests for MigrationManager path-change detection and data movement."""

import errno
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

from claude_wiki.config import ConfigManager, default_daily_dir
from claude_wiki.migration import MigrationManager
from claude_wiki.models import ProjectConfig


def _fake_stat_result(real: os.stat_result, *, st_dev: int) -> os.stat_result:
    """Return a stat result with overridden st_dev."""
    return os.stat_result(
        (
            real.st_mode,
            real.st_ino,
            st_dev,
            real.st_nlink,
            real.st_uid,
            real.st_gid,
            real.st_size,
            real.st_atime,
            real.st_mtime,
            real.st_ctime,
        )
    )


class FakeConfigManager:
    """Test double for ConfigManager that resolves 'user' to a fixed XDG-like path."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def get_kb_root(self, _repo_root: Path, config: ProjectConfig) -> Path:
        if str(config.kb_dir) == "user":
            return Path.home() / ".local" / "share" / "claude-wiki" / "local" / "test"
        return self.repo / "project"

    def get_machine_state_dir(self, _repo_root: Path, _config: ProjectConfig) -> Path:
        """Return a stable state dir so existing user-mode tests keep working."""
        return self.repo / ".claude" / "state"


class TestMigrationManager:
    """Tests for migration detection and execution."""

    def test_no_migration_when_no_previous_state(self):
        """No migration when there is no previous state."""
        mgr = MigrationManager()
        current = ProjectConfig(repo_name="test")

        result = mgr.check_and_migrate(Path("/fake"), current, None, dry_run=False)
        assert not result.migrated
        assert result.old_kb_dir is None
        assert result.new_kb_dir is None

    def test_no_migration_when_paths_unchanged(self):
        """No migration when kb_dir and daily_dir are identical."""
        mgr = MigrationManager()
        current = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )

        result = mgr.check_and_migrate(Path("/fake"), current, previous, dry_run=False)
        assert not result.migrated

    def test_migration_kb_dir_change_relative(self):
        """Migrate when kb_dir changes (relative path)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            new_kb = repo / "wiki"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.old_kb_dir == old_kb
            assert result.new_kb_dir == new_kb
            assert not result.errors
            assert new_kb.exists()
            assert (new_kb / "test.md").exists()
            assert not old_kb.exists()

    def test_migration_rewrites_catalog_self_links(self):
        """A catalog with [[index]] self-links has them rewritten on rename."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text(
                "# Index\n\nSee [[index#toc]] and [[index|top]]."
            )
            new_kb = repo / "wiki"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            mgr.check_and_migrate(repo, current, previous, dry_run=False)

            content = (new_kb / "test.md").read_text()
            assert "[[test#toc]]" in content
            assert "[[test|top]]" in content
            assert "[[index" not in content

    def test_migration_daily_dir_change_relative(self):
        """Migrate when daily_dir changes (relative path)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_daily = repo / "daily"
            old_daily.mkdir()
            (old_daily / "2024-01-01.md").write_text("log")
            new_daily = repo / "logs"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("logs")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.old_daily_dir == old_daily
            assert result.new_daily_dir == new_daily
            assert not result.errors
            assert new_daily.exists()
            assert (new_daily / "2024-01-01.md").exists()
            assert not old_daily.exists()

    def test_migration_both_dirs_change(self):
        """Migrate when both kb_dir and daily_dir change."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            old_daily = repo / "daily"
            old_daily.mkdir()
            (old_daily / "2024-01-01.md").write_text("log")

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("logs")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.old_kb_dir == old_kb
            assert result.new_kb_dir == repo / "wiki"
            assert result.old_daily_dir == old_daily
            assert result.new_daily_dir == repo / "logs"
            assert not result.errors

    def test_migration_refused_on_overlap(self):
        """Refuse migration when new paths would overlap."""
        mgr = MigrationManager()
        current = ProjectConfig(
            repo_name="test", kb_dir=Path("same"), daily_dir=Path("same")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("old-kb"), daily_dir=Path("old-daily")
        )

        result = mgr.check_and_migrate(Path("/fake"), current, previous, dry_run=False)
        assert not result.migrated
        assert result.errors
        assert "overlap" in result.errors[0].lower()

    def test_dry_run_does_not_touch_disk(self):
        """Dry run reports but does not move files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=True)

            assert result.migrated
            assert old_kb.exists()
            assert not (repo / "wiki").exists()

    def test_migration_when_destination_empty(self):
        """Migrate when destination exists but is empty — contents end up at dst root, not dst/src."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            new_kb = repo / "wiki"
            new_kb.mkdir()  # exists but empty

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert not result.errors
            assert new_kb.exists()
            assert (new_kb / "test.md").exists()
            assert not old_kb.exists()
            assert not (new_kb / "knowledge").exists()  # must NOT be nested

    def test_warning_when_destination_exists(self):
        """Warn and report not-migrated when destination already exists and is not empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            new_kb = repo / "wiki"
            new_kb.mkdir()
            (new_kb / "existing.md").write_text("existing")

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert not result.migrated
            assert result.warnings
            assert "already exists" in result.warnings[0].lower()
            assert old_kb.exists()
            assert new_kb.exists()
            assert (new_kb / "existing.md").exists()

    def test_absolute_path_migration(self):
        """Migrate when paths are absolute."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            old_kb = Path(tmpdir) / "old-kb"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            new_kb = Path(tmpdir) / "new-kb"

            current = ProjectConfig(
                repo_name="test", kb_dir=new_kb, daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=old_kb, daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.old_kb_dir == old_kb
            assert result.new_kb_dir == new_kb
            assert new_kb.exists()
            assert not old_kb.exists()

    def test_kb_dir_user_mode_resolves_to_xdg(self):
        """kb_dir='user' resolves to XDG path, not repo-relative."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "project"
            old_kb.mkdir(parents=True)
            (old_kb / "index.md").write_text("# Index")
            xdg_kb = Path.home() / ".local" / "share" / "claude-wiki" / "local" / "test"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("user"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("project"), daily_dir=Path("daily")
            )

            mgr = MigrationManager(config_manager=FakeConfigManager(repo))  # type: ignore[arg-type]
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.old_kb_dir == repo / "project"
            assert result.new_kb_dir == xdg_kb
            assert not result.errors

    def test_kb_dir_user_mode_dry_run_shows_correct_path(self):
        """--dry-run with kb_dir='user' previews the XDG path when destination is empty."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "project"
            old_kb.mkdir(parents=True)
            (old_kb / "index.md").write_text("# Index")
            xdg_kb = Path.home() / ".local" / "share" / "claude-wiki" / "local" / "test"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("user"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("project"), daily_dir=Path("daily")
            )

            mgr = MigrationManager(config_manager=FakeConfigManager(repo))  # type: ignore[arg-type]
            result = mgr.check_and_migrate(repo, current, previous, dry_run=True)

            assert result.migrated
            assert result.old_kb_dir == old_kb
            assert result.new_kb_dir == xdg_kb
            assert not result.errors
            assert old_kb.exists()
            assert not xdg_kb.exists()

    def test_flag_driven_migration_with_reports_dir(self):
        """A config built from CLI flags migrates kb_dir and daily_dir and round-trips reports_dir."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            old_daily = repo / "daily"
            old_daily.mkdir()
            (old_daily / "2024-01-01.md").write_text("log")
            new_kb = repo / "wiki"
            new_daily = repo / "logs"

            current = ProjectConfig(
                repo_name="test",
                kb_dir=Path("wiki"),
                daily_dir=Path("logs"),
                reports_dir=Path("custom-reports"),
            )
            previous = ProjectConfig(
                repo_name="test",
                kb_dir=Path("knowledge"),
                daily_dir=Path("daily"),
                reports_dir=Path("reports"),
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.old_kb_dir == old_kb
            assert result.new_kb_dir == new_kb
            assert result.old_daily_dir == old_daily
            assert result.new_daily_dir == new_daily
            assert not result.errors
            assert new_kb.exists()
            assert (new_kb / "test.md").exists()
            assert new_daily.exists()
            assert (new_daily / "2024-01-01.md").exists()

    # ------------------------------------------------------------------
    # Issue #13: path comparison and safety bugs
    # ------------------------------------------------------------------

    def test_paths_resolved_before_comparison(self):
        """Equivalent paths written differently are not treated as a migration."""
        repo = Path("/fake")
        mgr = MigrationManager()
        current = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("/fake/knowledge"), daily_dir=Path("daily")
        )

        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)
        assert not result.migrated
        assert not result.errors

    def test_migration_refused_when_paths_contain_each_other(self):
        """Refuse migration when new paths are nested, not only when equal."""
        mgr = MigrationManager()
        current = ProjectConfig(
            repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("wiki/sub")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("old-kb"), daily_dir=Path("old-daily")
        )

        result = mgr.check_and_migrate(Path("/fake"), current, previous, dry_run=False)
        assert not result.migrated
        assert result.errors
        assert "overlap" in result.errors[0].lower()

    def test_destination_file_does_not_crash_iterdir(self):
        """A destination that exists as a file is treated as occupied, not crashed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            new_kb = repo / "wiki"
            new_kb.write_text("i am a file")

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert not result.migrated
            assert result.warnings
            assert "already exists" in result.warnings[0].lower()
            assert old_kb.exists()

    def test_kb_dir_mode_resolved_without_explicit_config_manager(self, monkeypatch):
        """MigrationManager() without an explicit config manager still resolves modes."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            xdg_base = Path(tmpdir) / "xdg"
            xdg_kb = xdg_base / "local" / "test"
            xdg_kb.mkdir(parents=True, exist_ok=True)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "old.md").write_text("old")

            monkeypatch.setattr(
                "claude_wiki.config.user_data_dir",
                lambda app, appauthor=False: xdg_base,
            )

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("user"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert result.migrated
            assert result.new_kb_dir == xdg_kb
            assert result.old_kb_dir == old_kb
            assert not result.errors

    # ------------------------------------------------------------------
    # Issue #14: destination non-empty must report migrated=False
    # ------------------------------------------------------------------

    def test_migrated_false_when_source_missing(self):
        """A changed path with no source directory is not a migration."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            new_kb = repo / "wiki"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert not result.migrated
            assert not result.errors
            assert not result.warnings
            assert not new_kb.exists()

    def test_dry_run_migrated_false_when_source_missing(self):
        """--dry-run with a missing source reports migrated=False, not True."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            new_kb = repo / "wiki"

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=True)

            assert not result.migrated
            assert not result.errors
            assert not result.warnings
            assert not new_kb.exists()

    def test_migrated_false_when_destination_non_empty(self):
        """A skipped move because the destination exists leaves migrated=False."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "index.md").write_text("# Index")
            new_kb = repo / "wiki"
            new_kb.mkdir()
            (new_kb / "existing.md").write_text("existing")

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert not result.migrated
            assert result.warnings
            assert not result.errors
            assert old_kb.exists()
            assert (new_kb / "existing.md").exists()

    # ------------------------------------------------------------------
    # Issue #15: rollback on partial failure
    # ------------------------------------------------------------------

    def test_rollback_on_partial_failure(self, monkeypatch):
        """A failed second move rolls back an already-completed first move."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "kb.md").write_text("kb content")
            new_kb = repo / "wiki"

            old_daily = repo / "daily"
            old_daily.mkdir()
            (old_daily / "2024-01-01.md").write_text("daily content")
            new_daily = repo / "logs"
            new_daily.mkdir()

            original_rename = os.rename

            def _failing_rename(
                src: str | os.PathLike[str],
                dst: str | os.PathLike[str],
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if Path(dst).name == "logs":
                    raise PermissionError(f"mock failure moving {src} -> {dst}")
                original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

            monkeypatch.setattr(os, "rename", _failing_rename)

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("logs")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert not result.migrated
            assert result.errors
            assert result.rolled_back
            # kb move was completed then rolled back
            assert old_kb.exists()
            assert (old_kb / "kb.md").exists()
            assert not new_kb.exists()
            # daily move failed
            assert old_daily.exists()
            assert (old_daily / "2024-01-01.md").exists()

    def test_rollback_reports_its_own_errors(self, monkeypatch):
        """A rollback failure appends an error to the result."""
        import claude_wiki.migration as migration_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "kb.md").write_text("kb content")
            new_kb = repo / "wiki"

            old_daily = repo / "daily"
            old_daily.mkdir()
            (old_daily / "2024-01-01.md").write_text("daily content")
            new_daily = repo / "logs"
            new_daily.mkdir()

            original_rename = migration_mod.os.rename
            original_move = migration_mod.shutil.move

            def _failing_rename(
                src: str | os.PathLike[str],
                dst: str | os.PathLike[str],
                *,
                src_dir_fd: int | None = None,
                dst_dir_fd: int | None = None,
            ) -> None:
                if Path(dst).name == "logs":
                    raise PermissionError(f"mock failure moving {src} -> {dst}")
                original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

            def _failing_move(
                src: str | os.PathLike[str], dst: str | os.PathLike[str]
            ) -> str:
                if Path(src).resolve() == new_kb.resolve():
                    raise OSError("rollback blocked")
                return original_move(src, dst)

            monkeypatch.setattr(migration_mod.os, "rename", _failing_rename)
            monkeypatch.setattr(migration_mod.shutil, "move", _failing_move)

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("logs")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
            )

            mgr = MigrationManager()
            result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

            assert not result.migrated
            assert any(
                "rollback" in e.lower() and "blocked" in e.lower()
                for e in result.errors
            )

    def test_paths_overlap_when_nested(self):
        """_paths_overlap returns True when one path is inside the other."""
        mgr = MigrationManager()
        assert mgr._paths_overlap(Path("/a/b"), Path("/a")) is True
        assert mgr._paths_overlap(Path("/a"), Path("/a/b")) is True

    def test_paths_overlap_when_equal(self):
        """_paths_overlap returns True for identical paths."""
        mgr = MigrationManager()
        assert mgr._paths_overlap(Path("/a"), Path("/a")) is True

    def test_paths_overlap_case_insensitive_on_darwin_windows(self, monkeypatch):
        """_paths_overlap is case-insensitive on Windows and macOS."""
        import claude_wiki.migration as migration_mod

        monkeypatch.setattr(migration_mod, "_case_insensitive_paths", lambda: True)
        mgr = MigrationManager()
        assert mgr._paths_overlap(Path("/A/B"), Path("/a/b")) is True
        assert mgr._paths_overlap(Path("/A"), Path("/a/b")) is True
        assert mgr._paths_overlap(Path("/A"), Path("/b")) is False

    def test_paths_overlap_when_unrelated(self):
        """_paths_overlap returns False for unrelated paths."""
        mgr = MigrationManager()
        assert mgr._paths_overlap(Path("/a"), Path("/b")) is False

    def test_resolve_dir_relative_anchors_to_repo_root(self):
        """Relative paths resolve against repo_root."""
        mgr = MigrationManager()
        repo = Path("/fake/repo")
        assert mgr._resolve_dir(Path("daily"), repo) == repo / "daily"

    def test_resolve_dir_absolute_unchanged(self):
        """Absolute paths are returned unchanged."""
        mgr = MigrationManager()
        absolute = Path("/absolute/daily")
        assert mgr._resolve_dir(absolute, Path("/fake/repo")) == absolute

    # ------------------------------------------------------------------
    # Issue #70: machine-state directory moves with kb_dir mode switch
    # ------------------------------------------------------------------

    def test_state_dir_moved_on_kb_mode_switch(self, monkeypatch, tmp_path):
        """A project -> user mode switch also migrates the machine-state dir."""
        repo = tmp_path / "repo"
        repo.mkdir()
        xdg_data = tmp_path / "xdg-data"
        xdg_state = tmp_path / "xdg-state"

        def _fake_user_data_dir(app: str, appauthor: bool = False) -> Path:  # noqa: ARG001
            return xdg_data / app

        monkeypatch.setattr(
            "claude_wiki.config.user_data_dir",
            _fake_user_data_dir,
        )
        monkeypatch.setattr(
            "claude_wiki.config.user_state_dir",
            lambda app, appauthor=False: xdg_state,
        )

        old_kb = repo / ".claude" / "knowledge"
        old_kb.mkdir(parents=True)
        (old_kb / "index.md").write_text("# Index")
        old_daily = repo / ".claude" / "daily"
        old_daily.mkdir(parents=True)
        (old_daily / "2024-01-01.md").write_text("log")
        old_state = repo / ".claude" / "state"
        old_state.mkdir(parents=True)
        (old_state / "state.json").write_text("{}")
        (old_state / "logs").mkdir(parents=True)
        (old_state / "logs" / "compile.log").write_text("log")

        current = ProjectConfig(
            repo_name="test",
            repo_owner="local",
            kb_dir=Path("user"),
            daily_dir=default_daily_dir("user", "local", "test"),
        )
        previous = ProjectConfig(
            repo_name="test",
            repo_owner="local",
            kb_dir=Path("project"),
            daily_dir=Path(".claude/daily"),
        )

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)
        config_mgr = ConfigManager()

        assert result.migrated
        assert result.old_state_dir == old_state
        assert result.new_state_dir == config_mgr.get_machine_state_dir(repo, current)
        assert not result.errors
        assert not old_state.exists()
        assert (result.new_state_dir / "state.json").exists()
        assert (result.new_state_dir / "logs" / "compile.log").exists()

    def test_state_dir_rollback_on_failure(self, monkeypatch, tmp_path):
        """A failed state move rolls back already-completed kb/daily moves."""
        repo = tmp_path / "repo"
        repo.mkdir()
        xdg_data = tmp_path / "xdg-data"
        xdg_state = tmp_path / "xdg-state"

        def _fake_user_data_dir(app: str, appauthor: bool = False) -> Path:  # noqa: ARG001
            return xdg_data / app

        monkeypatch.setattr(
            "claude_wiki.config.user_data_dir",
            _fake_user_data_dir,
        )
        monkeypatch.setattr(
            "claude_wiki.config.user_state_dir",
            lambda app, appauthor=False: xdg_state,
        )

        old_kb = repo / ".claude" / "knowledge"
        old_kb.mkdir(parents=True)
        (old_kb / "index.md").write_text("# Index")
        old_daily = repo / ".claude" / "daily"
        old_daily.mkdir(parents=True)
        (old_daily / "2024-01-01.md").write_text("log")
        old_state = repo / ".claude" / "state"
        old_state.mkdir(parents=True)
        (old_state / "state.json").write_text("{}")
        (old_state / "logs").mkdir(parents=True)
        (old_state / "logs" / "compile.log").write_text("log")

        config_mgr = ConfigManager()
        current = ProjectConfig(
            repo_name="test",
            repo_owner="local",
            kb_dir=Path("user"),
            daily_dir=default_daily_dir("user", "local", "test"),
        )
        new_state = config_mgr.get_machine_state_dir(repo, current)

        previous = ProjectConfig(
            repo_name="test",
            repo_owner="local",
            kb_dir=Path("project"),
            daily_dir=Path(".claude/daily"),
        )

        original_rename = os.rename

        def _failing_rename(
            src: str | os.PathLike[str],
            dst: str | os.PathLike[str],
            *,
            src_dir_fd: int | None = None,
            dst_dir_fd: int | None = None,
        ) -> None:
            if Path(dst).resolve() == new_state.resolve():
                raise PermissionError(f"mock failure moving {src} -> {dst}")
            original_rename(src, dst, src_dir_fd=src_dir_fd, dst_dir_fd=dst_dir_fd)

        monkeypatch.setattr(os, "rename", _failing_rename)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

        assert not result.migrated
        assert result.errors
        assert result.rolled_back
        assert old_kb.exists()
        # kb_dir post-processing renamed index.md -> test.md before rollback.
        assert (old_kb / "test.md").exists()
        assert old_daily.exists()
        assert (old_daily / "2024-01-01.md").exists()
        assert old_state.exists()
        assert (old_state / "state.json").exists()

    def test_state_dir_dry_run_reports_move(self, monkeypatch, tmp_path, capsys):
        """Dry-run reports the prospective state_dir move without touching disk."""
        repo = tmp_path / "repo"
        repo.mkdir()
        xdg_data = tmp_path / "xdg-data"
        xdg_state = tmp_path / "xdg-state"

        def _fake_user_data_dir(app: str, appauthor: bool = False) -> Path:  # noqa: ARG001
            return xdg_data / app

        monkeypatch.setattr(
            "claude_wiki.config.user_data_dir",
            _fake_user_data_dir,
        )
        monkeypatch.setattr(
            "claude_wiki.config.user_state_dir",
            lambda app, appauthor=False: xdg_state,
        )

        old_kb = repo / ".claude" / "knowledge"
        old_kb.mkdir(parents=True)
        (old_kb / "index.md").write_text("# Index")
        old_daily = repo / ".claude" / "daily"
        old_daily.mkdir(parents=True)
        (old_daily / "2024-01-01.md").write_text("log")
        old_state = repo / ".claude" / "state"
        old_state.mkdir(parents=True)
        (old_state / "state.json").write_text("{}")

        current = ProjectConfig(
            repo_name="test",
            repo_owner="local",
            kb_dir=Path("user"),
            daily_dir=default_daily_dir("user", "local", "test"),
        )
        previous = ProjectConfig(
            repo_name="test",
            repo_owner="local",
            kb_dir=Path("project"),
            daily_dir=Path(".claude/daily"),
        )

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=True)
        config_mgr = ConfigManager()

        assert result.migrated
        assert result.old_state_dir == old_state
        assert result.new_state_dir == config_mgr.get_machine_state_dir(repo, current)
        assert old_kb.exists()
        assert old_daily.exists()
        assert old_state.exists()
        captured = capsys.readouterr()
        assert "Would move state_dir" in captured.out

    # ------------------------------------------------------------------
    # ADR-002: cross-filesystem pre-flight
    # ------------------------------------------------------------------

    def test_same_filesystem_uses_rename(self, monkeypatch, tmp_path):
        """Same-filesystem moves use os.rename and avoid shutil.move."""
        import claude_wiki.migration as migration_mod

        real_rename = os.rename
        real_stat = os.stat

        repo = tmp_path / "repo"
        repo.mkdir()
        old_kb = repo / "knowledge"
        old_kb.mkdir()
        (old_kb / "note.md").write_text("note")
        new_kb = repo / "wiki"

        rename_calls: list[tuple[str, str]] = []
        move_calls: list[tuple[str, str]] = []

        current = ProjectConfig(
            repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )

        def fake_rename(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            rename_calls.append((str(src), str(dst)))
            real_rename(src, dst)

        def fake_move(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> str:
            move_calls.append((str(src), str(dst)))
            return shutil.move(src, dst)

        def fake_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            p = Path(path)
            if p == old_kb or p == new_kb.parent:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=1)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(migration_mod.os, "stat", fake_stat)
        monkeypatch.setattr(migration_mod.os, "rename", fake_rename)
        monkeypatch.setattr(migration_mod.shutil, "move", fake_move)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

        assert result.migrated
        assert not result.errors
        assert any(
            src == str(old_kb) and dst == str(new_kb) for src, dst in rename_calls
        )
        assert not any(src == str(old_kb) for src, _ in move_calls)

    def test_cross_filesystem_without_force_is_refused(self, monkeypatch, tmp_path):
        """Cross-filesystem moves are refused unless --force is set."""
        import claude_wiki.migration as migration_mod

        real_stat = os.stat

        repo = tmp_path / "repo"
        repo.mkdir()
        old_kb = repo / "knowledge"
        old_kb.mkdir()
        new_kb_parent = tmp_path / "other"
        new_kb_parent.mkdir()
        new_kb = new_kb_parent / "wiki"

        current = ProjectConfig(
            repo_name="test", kb_dir=new_kb, daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=old_kb, daily_dir=Path("daily")
        )

        def fake_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            p = Path(path)
            if p == old_kb:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=1)
            if p == new_kb_parent:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=2)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(migration_mod.os, "stat", fake_stat)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

        assert not result.migrated
        assert result.errors
        assert any("Cross-filesystem" in e for e in result.errors)
        assert old_kb.exists()
        assert not new_kb.exists()

    def test_cross_filesystem_with_force_proceeds_with_warning(
        self, monkeypatch, tmp_path
    ):
        """Cross-filesystem moves with --force proceed with a best-effort warning."""
        import claude_wiki.migration as migration_mod

        real_stat = os.stat
        real_rename = os.rename

        repo = tmp_path / "repo"
        repo.mkdir()
        old_kb = repo / "knowledge"
        old_kb.mkdir()
        (old_kb / "note.md").write_text("note")
        new_kb_parent = tmp_path / "other"
        new_kb_parent.mkdir()
        new_kb = new_kb_parent / "wiki"

        current = ProjectConfig(
            repo_name="test", kb_dir=new_kb, daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=old_kb, daily_dir=Path("daily")
        )

        move_calls: list[tuple[str, str]] = []

        def fake_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            p = Path(path)
            if p == old_kb:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=1)
            if p == new_kb_parent:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=2)
            return real_stat(path, *args, **kwargs)

        def fake_move(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> str:
            move_calls.append((str(src), str(dst)))
            real_rename(src, dst)
            return str(dst)

        monkeypatch.setattr(migration_mod.os, "stat", fake_stat)
        monkeypatch.setattr(migration_mod.shutil, "move", fake_move)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(
            repo, current, previous, dry_run=False, force=True
        )

        assert result.migrated
        assert not result.errors
        assert any("best-effort" in w.lower() for w in result.warnings)
        assert any(src == str(old_kb) and dst == str(new_kb) for src, dst in move_calls)
        assert not old_kb.exists()
        assert new_kb.exists()
        assert (new_kb / "note.md").exists()

    def test_cross_filesystem_rollback_not_attempted(self, monkeypatch, tmp_path):
        """When force=True and a later move fails, do not roll back a cross-fs move."""
        import claude_wiki.migration as migration_mod

        real_rename = os.rename
        real_stat = os.stat

        repo = tmp_path / "repo"
        repo.mkdir()
        other = tmp_path / "other"
        other.mkdir()

        old_kb = repo / "knowledge"
        old_kb.mkdir()
        (old_kb / "kb.md").write_text("kb")
        new_kb = other / "wiki"

        old_daily = repo / "daily"
        old_daily.mkdir()
        (old_daily / "2024-01-01.md").write_text("daily")

        current = ProjectConfig(repo_name="test", kb_dir=new_kb, daily_dir=Path("logs"))
        previous = ProjectConfig(
            repo_name="test", kb_dir=old_kb, daily_dir=Path("daily")
        )

        def fake_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            p = Path(path)
            if p == old_kb:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=1)
            if p == other:
                real = real_stat(path, *args, **kwargs)
                return _fake_stat_result(real, st_dev=2)
            return real_stat(path, *args, **kwargs)

        def fake_move(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> str:
            if Path(src).resolve() == old_kb.resolve():
                real_rename(src, dst)
                return str(dst)
            raise AssertionError(f"Unexpected shutil.move call: {src} -> {dst}")

        def fake_rename(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            if Path(src).resolve() == old_daily.resolve():
                raise PermissionError(f"mock failure moving {src} -> {dst}")
            return real_rename(src, dst)

        monkeypatch.setattr(migration_mod.os, "stat", fake_stat)
        monkeypatch.setattr(migration_mod.shutil, "move", fake_move)
        monkeypatch.setattr(migration_mod.os, "rename", fake_rename)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(
            repo, current, previous, dry_run=False, force=True
        )

        assert not result.migrated
        assert result.errors
        assert not result.rolled_back
        # cross-fs kb move stays at its new location; same-fs daily move never happened
        assert not old_kb.exists()
        assert new_kb.exists()
        assert (new_kb / "kb.md").exists()
        assert old_daily.exists()
        assert (old_daily / "2024-01-01.md").exists()

    def test_existing_destination_compares_parent_device(self, monkeypatch, tmp_path):
        """When new_p already exists, pre-flight must stat new_p.parent, not new_p."""
        import claude_wiki.migration as migration_mod

        real_stat = os.stat

        repo = tmp_path / "repo"
        repo.mkdir()
        old_kb = repo / "knowledge"
        old_kb.mkdir()
        (old_kb / "note.md").write_text("note")
        new_kb = repo / "wiki"
        new_kb.mkdir()  # already exists

        current = ProjectConfig(
            repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )

        def fake_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            p = Path(path)
            real = real_stat(path, *args, **kwargs)
            if p == old_kb or p == new_kb.parent:
                return _fake_stat_result(real, st_dev=1)
            if p == new_kb:
                # A different device for the destination itself; parent must win.
                return _fake_stat_result(real, st_dev=2)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(migration_mod.os, "stat", fake_stat)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

        assert result.migrated
        assert not result.errors
        assert not result.warnings
        assert not old_kb.exists()
        assert (new_kb / "note.md").exists()

    def test_exdev_runtime_falls_back_to_shutil_move(self, monkeypatch, tmp_path):
        """If os.rename raises EXDEV at runtime, fall back to shutil.move."""
        import claude_wiki.migration as migration_mod

        real_stat = os.stat
        real_rename = os.rename

        repo = tmp_path / "repo"
        repo.mkdir()
        old_kb = repo / "knowledge"
        old_kb.mkdir()
        (old_kb / "note.md").write_text("note")
        new_kb = repo / "wiki"

        current = ProjectConfig(
            repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )

        rename_calls: list[tuple[str, str]] = []
        move_calls: list[tuple[str, str]] = []

        def fake_rename(
            src: str | os.PathLike[str], dst: str | os.PathLike[str]
        ) -> None:
            rename_calls.append((str(src), str(dst)))
            if Path(src).resolve() == old_kb.resolve():
                raise OSError(errno.EXDEV, "cross-device link not permitted")
            real_rename(src, dst)

        def fake_move(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> str:
            move_calls.append((str(src), str(dst)))
            real_rename(src, dst)
            return str(dst)

        def fake_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            p = Path(path)
            real = real_stat(path, *args, **kwargs)
            if p == old_kb or p == new_kb.parent:
                return _fake_stat_result(real, st_dev=1)
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(migration_mod.os, "stat", fake_stat)
        monkeypatch.setattr(migration_mod.os, "rename", fake_rename)
        monkeypatch.setattr(migration_mod.shutil, "move", fake_move)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

        assert result.migrated
        assert not result.errors
        assert any("Cross-filesystem move" in w for w in result.warnings)
        assert any(
            src == str(old_kb) and dst == str(new_kb) for src, dst in rename_calls
        )
        assert any(src == str(old_kb) and dst == str(new_kb) for src, dst in move_calls)
        assert not old_kb.exists()
        assert (new_kb / "note.md").exists()

    def test_preflight_stat_oserror_becomes_migration_error(
        self, monkeypatch, tmp_path
    ):
        """An OSError during pre-flight stat is surfaced as a migration error."""
        import claude_wiki.migration as migration_mod

        real_stat = os.stat

        repo = tmp_path / "repo"
        repo.mkdir()
        old_kb = repo / "knowledge"
        old_kb.mkdir()
        (old_kb / "note.md").write_text("note")

        current = ProjectConfig(
            repo_name="test", kb_dir=Path("wiki"), daily_dir=Path("daily")
        )
        previous = ProjectConfig(
            repo_name="test", kb_dir=Path("knowledge"), daily_dir=Path("daily")
        )

        def failing_stat(
            path: str | os.PathLike[str], *args: Any, **kwargs: Any
        ) -> os.stat_result:
            # Use path comparison without resolve() to avoid recursive os.stat
            # calls through pathlib internals on Python < 3.14.
            if Path(path) == repo:
                raise OSError(errno.EACCES, "permission denied")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(migration_mod.os, "stat", failing_stat)

        mgr = MigrationManager()
        result = mgr.check_and_migrate(repo, current, previous, dry_run=False)

        assert not result.migrated
        assert result.errors
        assert any("kb_dir" in e and "stat" in e.lower() for e in result.errors)
