"""Migration logic — moves data when config paths change."""

from __future__ import annotations

import shutil
from pathlib import Path

from claude_wiki.config import ConfigManager
from claude_wiki.interfaces import Migrator
from claude_wiki.models import MigrationResult, ProjectConfig


class MigrationManager(Migrator):
    """Detects path changes between config versions and migrates data."""

    def __init__(self, config_manager: ConfigManager | None = None) -> None:
        self.config_manager = (
            config_manager if config_manager is not None else ConfigManager()
        )

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
            previous: The last known config (from the lock file), or None.
            dry_run: When True, report what would move without touching disk.
        """
        if previous is None:
            return MigrationResult(migrated=False)

        old_kb = self._resolve_kb_dir(previous, repo_root).resolve(strict=False)
        new_kb = self._resolve_kb_dir(current, repo_root).resolve(strict=False)
        old_daily = self._resolve_dir(previous.daily_dir, repo_root).resolve(
            strict=False
        )
        new_daily = self._resolve_dir(current.daily_dir, repo_root).resolve(
            strict=False
        )

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

        # Validate: never migrate into each other (equality or containment)
        if kb_changed and daily_changed:
            if (
                self._paths_overlap(new_kb, new_daily)
                or self._paths_overlap(old_kb, new_daily)
                or self._paths_overlap(old_daily, new_kb)
            ):
                return MigrationResult(
                    migrated=False,
                    errors=["Migration refused: kb_dir and daily_dir would overlap."],
                )

        completed_moves: list[tuple[str, Path, Path]] = []

        if kb_changed:
            result, moved = self._migrate_dir(
                old_kb, new_kb, result, label="kb_dir", dry_run=dry_run
            )
            if moved:
                completed_moves.append(("kb_dir", old_kb, new_kb))

        if daily_changed and not result.errors:
            result, moved = self._migrate_dir(
                old_daily, new_daily, result, label="daily_dir", dry_run=dry_run
            )
            if moved:
                completed_moves.append(("daily_dir", old_daily, new_daily))

        if result.errors and completed_moves and not dry_run:
            rollback_errors = self._rollback(completed_moves)
            result = MigrationResult(
                migrated=False,
                old_kb_dir=result.old_kb_dir,
                new_kb_dir=result.new_kb_dir,
                old_daily_dir=result.old_daily_dir,
                new_daily_dir=result.new_daily_dir,
                errors=[*result.errors, *rollback_errors],
                warnings=result.warnings,
                rolled_back=[(label, src, dst) for label, src, dst in completed_moves],
            )

        return result

    def _migrate_dir(
        self,
        src: Path,
        dst: Path,
        result: MigrationResult,
        *,
        label: str,
        dry_run: bool,
    ) -> tuple[MigrationResult, bool]:
        """Move contents from src to dst, collecting warnings/errors.

        Returns:
            A tuple of (updated result, bool indicating whether a move happened or would happen).
        """
        if not src.exists():
            # Nothing to migrate
            return result, False

        if dst.exists():
            if not dst.is_dir() or any(dst.iterdir()):
                # Destination already exists and is not an empty dir — warn but do not overwrite
                warnings = [
                    *result.warnings,
                    f"{label}: destination {dst} already exists and is not empty — skipping.",
                ]
                return (
                    MigrationResult(
                        migrated=False,
                        old_kb_dir=result.old_kb_dir,
                        new_kb_dir=result.new_kb_dir,
                        old_daily_dir=result.old_daily_dir,
                        new_daily_dir=result.new_daily_dir,
                        errors=result.errors,
                        warnings=warnings,
                    ),
                    False,
                )
            elif not dry_run:
                # Empty destination directory — remove so shutil.move places src at dst root
                dst.rmdir()

        if dry_run:
            print(f"[dry-run] Would move {label}: {src} -> {dst}")
            return result, True

        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        except OSError as exc:
            errors = [*result.errors, f"{label}: failed to move {src} -> {dst}: {exc}"]
            return (
                MigrationResult(
                    migrated=False,
                    old_kb_dir=result.old_kb_dir,
                    new_kb_dir=result.new_kb_dir,
                    old_daily_dir=result.old_daily_dir,
                    new_daily_dir=result.new_daily_dir,
                    errors=errors,
                    warnings=result.warnings,
                ),
                False,
            )

        return result, True

    def _rollback(self, completed_moves: list[tuple[str, Path, Path]]) -> list[str]:
        """Reverse already-completed moves in LIFO order.

        Returns a list of error messages for any rollback failures.
        """
        errors: list[str] = []
        for label, src, dst in reversed(completed_moves):
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(dst), str(src))
            except OSError as exc:
                errors.append(f"{label}: rollback failed {dst} -> {src}: {exc}")
        return errors

    @staticmethod
    def _paths_overlap(a: Path, b: Path) -> bool:
        """Return True if a and b are the same path or one is inside the other."""
        if a == b:
            return True
        try:
            a.relative_to(b)
            return True
        except ValueError:
            pass
        try:
            b.relative_to(a)
            return True
        except ValueError:
            return False

    def _resolve_kb_dir(self, config: ProjectConfig, repo_root: Path) -> Path:
        """Resolve kb_dir using ConfigManager."""
        return self.config_manager.get_kb_root(repo_root, config)

    @staticmethod
    def _resolve_dir(path: Path, repo_root: Path) -> Path:
        """Return absolute path — relative paths are anchored at repo_root."""
        if path.is_absolute():
            return path
        return repo_root / path
