"""Migration logic — moves data when config paths change."""

from __future__ import annotations

import shutil
from pathlib import Path

from claude_wiki.catalog_utils import rewrite_index_wikilinks
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
        old_state = self.config_manager.get_machine_state_dir(
            repo_root, previous
        ).resolve(strict=False)
        new_state = self.config_manager.get_machine_state_dir(
            repo_root, current
        ).resolve(strict=False)

        kb_changed = old_kb != new_kb
        daily_changed = old_daily != new_daily
        state_changed = old_state != new_state

        if not kb_changed and not daily_changed and not state_changed:
            return MigrationResult(migrated=False)

        result = MigrationResult(
            migrated=True,
            old_kb_dir=old_kb if kb_changed else None,
            new_kb_dir=new_kb if kb_changed else None,
            old_daily_dir=old_daily if daily_changed else None,
            new_daily_dir=new_daily if daily_changed else None,
            old_state_dir=old_state if state_changed else None,
            new_state_dir=new_state if state_changed else None,
        )

        # Validate: never migrate into each other (equality or containment)
        path_specs = [
            ("kb_dir", old_kb, new_kb, kb_changed),
            ("daily_dir", old_daily, new_daily, daily_changed),
            ("state_dir", old_state, new_state, state_changed),
        ]
        changed_specs = [
            (label, old_p, new_p)
            for label, old_p, new_p, changed in path_specs
            if changed
        ]
        all_specs = [
            (label, old_p, new_p) for label, old_p, new_p, _changed in path_specs
        ]
        for i, (label_a, _old_a, new_a) in enumerate(changed_specs):
            for label_b, _old_b, new_b in changed_specs[i + 1 :]:
                if self._paths_overlap(new_a, new_b):
                    return MigrationResult(
                        migrated=False,
                        errors=[
                            f"Migration refused: {label_a} and {label_b} would overlap."
                        ],
                    )
            for label_b, old_b, _new_b in all_specs:
                if label_a != label_b and self._paths_overlap(new_a, old_b):
                    return MigrationResult(
                        migrated=False,
                        errors=[
                            f"Migration refused: {label_a} and {label_b} would overlap."
                        ],
                    )

        completed_moves: list[tuple[str, Path, Path]] = []

        if kb_changed:
            result, moved = self._migrate_dir(
                old_kb, new_kb, result, label="kb_dir", dry_run=dry_run
            )
            if moved:
                completed_moves.append(("kb_dir", old_kb, new_kb))
                if not dry_run and not result.errors:
                    self._post_process_kb_rename(new_kb, current.repo_name)

        if daily_changed and not result.errors:
            result, moved = self._migrate_dir(
                old_daily, new_daily, result, label="daily_dir", dry_run=dry_run
            )
            if moved:
                completed_moves.append(("daily_dir", old_daily, new_daily))

        if state_changed and not result.errors:
            result, moved = self._migrate_dir(
                old_state, new_state, result, label="state_dir", dry_run=dry_run
            )
            if moved:
                completed_moves.append(("state_dir", old_state, new_state))

        if result.errors and completed_moves and not dry_run:
            rollback_errors = self._rollback(completed_moves)
            result = MigrationResult(
                migrated=False,
                old_kb_dir=result.old_kb_dir,
                new_kb_dir=result.new_kb_dir,
                old_daily_dir=result.old_daily_dir,
                new_daily_dir=result.new_daily_dir,
                old_state_dir=result.old_state_dir,
                new_state_dir=result.new_state_dir,
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
                        old_state_dir=result.old_state_dir,
                        new_state_dir=result.new_state_dir,
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
                    old_state_dir=result.old_state_dir,
                    new_state_dir=result.new_state_dir,
                    errors=errors,
                    warnings=result.warnings,
                ),
                False,
            )

        return result, True

    def _post_process_kb_rename(self, kb_root: Path, repo_name: str) -> None:
        """After a kb_dir move, rename index.md to {repo_name}.md and rewrite wikilinks."""
        legacy = kb_root / "index.md"
        primary = kb_root / f"{repo_name}.md"
        if not legacy.exists() or primary.exists():
            return
        legacy.rename(primary)
        for subdir_name in ("concepts", "connections", "qa"):
            subdir = kb_root / subdir_name
            if not subdir.exists():
                continue
            for article in subdir.glob("*.md"):
                content = article.read_text(encoding="utf-8")
                new_content = rewrite_index_wikilinks(content, repo_name)
                if new_content != content:
                    article.write_text(new_content, encoding="utf-8")

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
