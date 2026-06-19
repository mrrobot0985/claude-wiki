"""Tests for MigrationManager path-change detection and data movement."""

import tempfile
from pathlib import Path


from claude_wiki.migration import MigrationManager
from claude_wiki.models import ProjectConfig


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

    def test_warning_when_destination_exists(self):
        """Warn when destination already exists and is not empty."""
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

            assert result.migrated
            assert result.warnings
            assert "already exists" in result.warnings[0].lower()
            assert old_kb.exists()

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
