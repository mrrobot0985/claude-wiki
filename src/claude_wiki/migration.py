"""Migration logic — moves data when config paths change."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from claude_wiki.interfaces import Migrator
from claude_wiki.models import MigrationResult, ProjectConfig


class MigrationManager(Migrator):
    """Detects path changes between config versions and migrates data."""

    _STATE_NAME = ".claude-wiki.state.json"

    def check_and_migrate(
        self,
        repo_root: Path,
        current: ProjectConfig,
        previous: ProjectConfig | None,
        *,
        dry_run: bool = False,
    ) -> MigrationResult:
        """Compare configs and move data if kb_dir or daily_dir changed.

        Args:
            repo_root: Repository root containing .claude-wiki.lock.
            current: The freshly loaded/current config.
            previous: The last known config (from state file), or None.
            dry_run: When True, report what would move without touching disk.
        """
        if previous is None:
            return MigrationResult(migrated=False)

        old_kb = self._resolve_dir(previous.kb_dir, repo_root)
        new_kb = self._resolve_dir(current.kb_dir, repo_root)
        old_daily = self._resolve_dir(previous.daily_dir, repo_root)
        new_daily = self._resolve_dir(current.daily_dir, repo_root)

        kb_changed = old_kb != new_kb
        daily_changed = old_daily != new_daily

        if not kb_changed and not daily_changed:
            return MigrationResult(migrated=False)

        result = MigrationResult(
            migrated=True,
            old_kb_dir=old_kb if kb_changed else None,
            new_kb_dir=new_kb if kb_changed else None,
            old_daily_dir=old_daily if daily_changed else None,
            new_daily_dir=new_daily if daily_changed else None,
        )

        # Validate: never migrate into each other
        if kb_changed and daily_changed:
            if new_kb == new_daily or old_kb == new_daily or old_daily == new_kb:
                return MigrationResult(
                    migrated=False,
                    errors=["Migration refused: kb_dir and daily_dir would overlap."],
                )

        if kb_changed:
            result = self._migrate_dir(
                old_kb, new_kb, result, label="kb_dir", dry_run=dry_run
            )
        if daily_changed:
            result = self._migrate_dir(
                old_daily, new_daily, result, label="daily_dir", dry_run=dry_run
            )

        if not dry_run and not result.errors:
            self.save_state(repo_root, current)

        return result

    def _migrate_dir(
        self,
        src: Path,
        dst: Path,
        result: MigrationResult,
        *,
        label: str,
        dry_run: bool,
    ) -> MigrationResult:
        """Move contents from src to dst, collecting warnings/errors."""
        if not src.exists():
            # Nothing to migrate
            return result

        if dst.exists() and any(dst.iterdir()):
            # Destination already has data — warn but do not overwrite
            warnings = [*result.warnings, f"{label}: destination {dst} already exists and is not empty — skipping."]
            return MigrationResult(
                migrated=result.migrated,
                old_kb_dir=result.old_kb_dir,
                new_kb_dir=result.new_kb_dir,
                old_daily_dir=result.old_daily_dir,
                new_daily_dir=result.new_daily_dir,
                errors=result.errors,
                warnings=warnings,
            )

        if dry_run:
            print(f"[dry-run] Would move {label}: {src} -> {dst}")
            return result

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            errors = [*result.errors, f"{label}: failed to move {src} -> {dst}: {exc}"]
            return MigrationResult(
                migrated=result.migrated,
                old_kb_dir=result.old_kb_dir,
                new_kb_dir=result.new_kb_dir,
                old_daily_dir=result.old_daily_dir,
                new_daily_dir=result.new_daily_dir,
                errors=errors,
                warnings=result.warnings,
            )

        return result

    def save_state(self, repo_root: Path, config: ProjectConfig) -> None:
        """Persist a snapshot of the current config for future comparison."""
        state_file = repo_root / self._STATE_NAME
        state_file.write_text(json.dumps(config.to_dict(), indent=2))

    def load_state(self, repo_root: Path) -> ProjectConfig | None:
        """Load the previously saved config snapshot, if any."""
        state_file = repo_root / self._STATE_NAME
        if not state_file.exists():
            return None
        try:
            data = json.loads(state_file.read_text())
            return ProjectConfig.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    @staticmethod
    def _resolve_dir(path: Path, repo_root: Path) -> Path:
        """Return absolute path — relative paths are anchored at repo_root."""
        if path.is_absolute():
            return path
        return repo_root / path
