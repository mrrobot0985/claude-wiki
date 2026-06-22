"""Configuration I/O and path resolution."""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path

from platformdirs import user_cache_dir, user_data_dir, user_state_dir

from claude_wiki.errors import ConfigError, RepoNotFoundError
from claude_wiki.git_utils import infer_repo_owner
from claude_wiki.interfaces import ConfigLoader, RepoDetector
from claude_wiki.models import ProjectConfig

logger = logging.getLogger(__name__)


def default_daily_dir(kb_mode: str, repo_owner: str, repo_name: str) -> Path:
    """Return the canonical daily log directory for a KB mode.

    - ``user`` mode → ``~/.local/share/claude-wiki-daily/<owner>/<repo>/``
    - any other mode → ``.claude/daily`` (repo-relative)
    """
    if kb_mode == "user":
        return (
            Path(user_data_dir("claude-wiki-daily", appauthor=False))
            / repo_owner
            / repo_name
        )
    return Path(".claude/daily")


class ConfigManager(RepoDetector, ConfigLoader):
    """Concrete implementation: walks filesystem, resolves XDG paths."""

    @staticmethod
    def resolve_repo_path(path: Path, repo_root: Path | None = None) -> Path:
        """Resolve a repo-relative path: absolute paths kept as-is;
        relative paths resolved against repo_root (or cwd if None).
        """
        path = path.expanduser()
        if path.is_absolute():
            return path.resolve(strict=False)
        if repo_root is not None:
            return (repo_root / path).resolve(strict=False)
        return path.resolve(strict=False)

    def find_repo_root(self, start: Path) -> Path:
        """Walk upward looking for .git or .claude-wiki.lock."""
        current = start.resolve()
        while True:
            if (current / ".git").exists() or (current / ".claude-wiki.lock").exists():
                return current
            parent = current.parent
            if parent == current:
                raise RepoNotFoundError(
                    f"Not in a git repo: no .git or .claude-wiki.lock found from {start}"
                )
            current = parent

    def load(self, repo_root: Path) -> ProjectConfig:
        """Read .claude-wiki.lock if present, else infer defaults."""
        marker = repo_root / ".claude-wiki.lock"
        if marker.exists():
            try:
                data = json.loads(marker.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ConfigError(
                    f"Corrupt lock file {marker.resolve(strict=False)}: {e}"
                ) from e
            defaults = {
                "repo_owner": "local",
                "layout_version": "2",
                "kb_dir": "project",
                "daily_dir": "daily",
                "reports_dir": "reports",
                "timezone": "UTC",
                "compile_after_hour": 18,
            }
            # Mode-aware daily_dir default for legacy lock files without explicit value
            kb_mode = str(data.get("kb_dir", "project"))
            if "daily_dir" not in data:
                owner = data.get("repo_owner", "local")
                name = data.get("repo_name", repo_root.name)
                defaults["daily_dir"] = str(default_daily_dir(kb_mode, owner, name))
            env_daily = os.environ.get("CLAUDE_WIKI_DAILY_DIR")
            if env_daily:
                defaults["daily_dir"] = env_daily
            merged = {**defaults, **data}
            config = ProjectConfig.from_dict(merged)
        else:
            # Infer from git remote, falling back to directory name + local owner.
            inferred_owner = infer_repo_owner(repo_root)
            config = ProjectConfig(
                repo_name=repo_root.name,
                repo_owner=inferred_owner,
                daily_dir=Path(".claude/daily"),
            )
        if self._maybe_migrate_legacy(repo_root, config):
            config = ProjectConfig.from_dict(
                {**config.to_dict(), "layout_version": "2"}
            )
        return config

    def write(self, repo_root: Path, config: ProjectConfig) -> None:
        """Persist .claude-wiki.lock atomically via a sibling temp file."""
        marker = repo_root / ".claude-wiki.lock"
        temp = marker.with_suffix(".lock.tmp")
        temp.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        os.replace(temp, marker)

    def _maybe_migrate_legacy(self, repo_root: Path, config: ProjectConfig) -> bool:
        """Lazy migration from layout_version 1 to 2.

        Moves legacy user-mode vaults, state.json, logs/, reports/, and
        repo/daily to their ADR-005 locations.  Idempotent and atomic with
        respect to the lock file: any move failure prevents the
        layout_version bump.
        """
        if config.layout_version not in (None, "", "1"):
            return False

        errors: list[str] = []
        warnings: list[str] = []
        migrated = False
        completed_moves: list[tuple[str, Path, Path]] = []

        kb_mode = str(config.kb_dir.expanduser())
        is_user_mode = kb_mode == "user"

        if is_user_mode:
            old_kb_root = (
                Path(user_data_dir("claude-wiki", appauthor=False))
                / config.repo_owner
                / config.repo_name
            ).resolve(strict=False)
        else:
            old_kb_root = self.get_kb_root(repo_root, config)

        kb_root = self.get_kb_root(repo_root, config)
        state_dir = self.get_machine_state_dir(repo_root, config)
        cache_dir = self.get_cache_dir(repo_root, config)
        daily_dir = self.resolve_repo_path(config.daily_dir, repo_root)

        def move_dir(src: Path, dst: Path, label: str) -> None:
            nonlocal migrated, errors, warnings
            if not src.exists():
                return
            if dst.exists():
                warnings.append(f"{label}: target {dst} already exists — skipping")
                return
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                migrated = True
                completed_moves.append((label, src, dst))
            except OSError as exc:
                errors.append(f"{label}: failed to move {src} -> {dst}: {exc}")

        def move_file(src: Path, dst: Path, label: str) -> None:
            nonlocal migrated, errors, warnings
            if not src.exists():
                return
            if dst.exists():
                warnings.append(f"{label}: target {dst} already exists — skipping")
                return
            try:
                dst.parent.mkdir(parents=True, exist_ok=True)
                temp = dst.with_suffix(".tmp")
                temp.write_bytes(src.read_bytes())
                os.replace(temp, dst)
                src.unlink()
                migrated = True
                completed_moves.append((label, src, dst))
            except OSError as exc:
                errors.append(f"{label}: failed to move {src} -> {dst}: {exc}")

        # Legacy user-mode vault used the "claude-wiki" namespace.
        if is_user_mode and old_kb_root != kb_root:
            move_dir(old_kb_root, kb_root, "vault")

        # Separate machine-state and cache out of the KB root.
        move_file(kb_root / "state.json", state_dir / "state.json", "state.json")
        move_dir(kb_root / "logs", state_dir / "logs", "logs")
        move_dir(kb_root / "reports", cache_dir / "reports", "reports")

        # Legacy user-mode daily logs lived next to the repository root.
        if is_user_mode:
            move_dir(repo_root / "daily", daily_dir, "daily")

        for warning in warnings:
            logger.warning("Legacy migration: %s", warning)

        if errors:
            if completed_moves:
                rollback_errors = self._rollback(completed_moves)
                errors.extend(rollback_errors)
            logger.error(
                "Legacy migration failed for %s: %s",
                repo_root,
                "; ".join(errors),
            )
            return False

        # Bump layout_version even when no files needed moving so that the
        # next load() is a no-op.
        new_config = ProjectConfig(
            repo_name=config.repo_name,
            repo_owner=config.repo_owner,
            layout_version="2",
            kb_dir=config.kb_dir,
            daily_dir=config.daily_dir,
            reports_dir=config.reports_dir,
            timezone=config.timezone,
            compile_after_hour=config.compile_after_hour,
        )
        self.write(repo_root, new_config)
        logger.info("Migrated legacy layout to version 2 for %s", repo_root)
        return True

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

    def get_kb_root(self, repo_root: Path, config: ProjectConfig) -> Path:
        """Resolve KB directory: env > absolute config > mode-based.

        Modes:
          - "user"    → XDG: ~/.local/share/claude-wiki-vault/<owner>/<repo>/
          - "project" → repo-relative: <repo>/.claude/knowledge/
          - absolute  → exact path
          - relative  → repo_root / path
        """
        # Priority 1: environment override
        env_dir = os.environ.get("CLAUDE_WIKI_PROJECT_DIR")
        if env_dir:
            return Path(env_dir).expanduser().resolve(strict=False)

        # Priority 2: absolute path in config (expand ~ before testing absoluteness)
        kb_dir = config.kb_dir.expanduser()
        if kb_dir.is_absolute():
            return kb_dir.resolve(strict=False)

        # Priority 3: mode-based resolution
        kb_str = str(kb_dir)
        if kb_str == "user":
            base = Path(user_data_dir("claude-wiki-vault", appauthor=False))
            return (base / config.repo_owner / config.repo_name).resolve(strict=False)
        if kb_str == "project":
            return (repo_root / ".claude" / "knowledge").resolve(strict=False)

        # Fallback: relative path anchored at repo_root
        return (repo_root / kb_dir).resolve(strict=False)

    def get_machine_state_dir(self, repo_root: Path, config: ProjectConfig) -> Path:
        """Resolve machine-state directory for logs, hashes, and compilation state.

        Modes:
          - "user"    → XDG state: ~/.local/state/claude-wiki/repos/<o>/<r>/
          - "project" → repo-relative: <repo>/.claude/state/
          - env var   → CLAUDE_WIKI_STATE_DIR overrides everything
        """
        env_dir = os.environ.get("CLAUDE_WIKI_STATE_DIR")
        if env_dir:
            return Path(env_dir).expanduser().resolve(strict=False)

        kb_dir = config.kb_dir.expanduser()
        if str(kb_dir) == "user":
            base = Path(user_state_dir("claude-wiki", appauthor=False))
            return (base / "repos" / config.repo_owner / config.repo_name).resolve(
                strict=False
            )

        return (repo_root / ".claude" / "state").resolve(strict=False)

    def get_cache_dir(self, repo_root: Path, config: ProjectConfig) -> Path:
        """Resolve cache directory for ephemeral reports and temp files.

        Modes:
          - "user"    → XDG cache: ~/.cache/claude-wiki/repos/<o>/<r>/
          - "project" → repo-relative: <repo>/.claude/reports/
          - env var   → CLAUDE_WIKI_CACHE_DIR overrides everything
        """
        env_dir = os.environ.get("CLAUDE_WIKI_CACHE_DIR")
        if env_dir:
            return Path(env_dir).expanduser().resolve(strict=False)

        kb_dir = config.kb_dir.expanduser()
        if str(kb_dir) == "user":
            base = Path(user_cache_dir("claude-wiki", appauthor=False))
            return (base / "repos" / config.repo_owner / config.repo_name).resolve(
                strict=False
            )

        return (repo_root / ".claude").resolve(strict=False)
