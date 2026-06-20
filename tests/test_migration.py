"""Tests for MigrationManager path-change detection and data movement."""

import tempfile
from pathlib import Path


from claude_wiki.migration import MigrationManager
from claude_wiki.models import ProjectConfig


class FakeConfigManager:
    """Test double for ConfigManager that resolves 'user' to a fixed XDG-like path."""

    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def get_kb_root(self, _repo_root: Path, config: ProjectConfig) -> Path:
        if str(config.kb_dir) == "user":
            return Path.home() / ".local" / "share" / "claude-wiki" / "local" / "test"
        return self.repo / "project"


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
            assert (new_kb / "index.md").exists()
            assert not old_kb.exists()

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
            assert (new_kb / "index.md").exists()
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
            xdg_kb = Path.home() / ".local" / "share" / "claude-wiki" / "local" / "test"
            xdg_kb.mkdir(parents=True, exist_ok=True)
            (xdg_kb / "index.md").write_text("# Index")

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
            xdg_kb = Path.home() / ".local" / "share" / "claude-wiki" / "local" / "test"
            xdg_kb.mkdir(parents=True, exist_ok=True)

            current = ProjectConfig(
                repo_name="test", kb_dir=Path("user"), daily_dir=Path("daily")
            )
            previous = ProjectConfig(
                repo_name="test", kb_dir=Path("project"), daily_dir=Path("daily")
            )

            mgr = MigrationManager(config_manager=FakeConfigManager(repo))  # type: ignore[arg-type]
            result = mgr.check_and_migrate(repo, current, previous, dry_run=True)

            assert result.migrated
            assert result.new_kb_dir == xdg_kb
            assert not result.errors

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
            assert (new_kb / "index.md").exists()
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
            repo_name="test", kb_dir=Path("repo/../knowledge"), daily_dir=Path("daily")
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
        import shutil as _shutil

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

            original_move = _shutil.move

            def _failing_move(src, dst, **kwargs):
                if Path(dst).name == "logs":
                    raise PermissionError(f"mock failure moving {src} -> {dst}")
                return original_move(src, dst, **kwargs)

            monkeypatch.setattr(_shutil, "move", _failing_move)

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
        import shutil as _shutil

        original_move = _shutil.move

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir)
            old_kb = repo / "knowledge"
            old_kb.mkdir()
            (old_kb / "kb.md").write_text("kb content")

            old_daily = repo / "daily"
            old_daily.mkdir()
            (old_daily / "2024-01-01.md").write_text("daily content")
            new_daily = repo / "logs"
            new_daily.mkdir()

            def _failing_move(src, dst, **kwargs):
                if Path(dst).name == "logs":
                    raise PermissionError(f"mock failure moving {src} -> {dst}")
                # Let the first move succeed, but make rollback fail.
                if Path(dst).name == "knowledge":
                    raise OSError("rollback blocked")
                return original_move(src, dst, **kwargs)

            monkeypatch.setattr(_shutil, "move", _failing_move)

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
