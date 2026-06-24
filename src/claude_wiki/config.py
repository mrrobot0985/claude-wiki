"""Configuration I/O and path resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from platformdirs import user_cache_dir, user_data_dir, user_state_dir

from claude_wiki.errors import ConfigError, RepoNotFoundError
from claude_wiki.git_utils import infer_repo_owner
from claude_wiki.models import ProjectConfig


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


class ConfigManager:
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
            config = self._build_config(repo_root, data)
        else:
            # Infer from git remote, falling back to directory name + local owner.
            inferred_owner = infer_repo_owner(repo_root)
            config = ProjectConfig(
                repo_name=repo_root.name,
                repo_owner=inferred_owner,
                daily_dir=Path(".claude/daily"),
            )
        return config

    def _build_config(self, repo_root: Path, data: dict[str, Any]) -> ProjectConfig:
        """Merge raw lock JSON with defaults and return a ProjectConfig."""
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
        return ProjectConfig.from_dict(merged)

    def write(self, repo_root: Path, config: ProjectConfig) -> None:
        """Persist .claude-wiki.lock atomically via a sibling temp file."""
        marker = repo_root / ".claude-wiki.lock"
        temp = marker.with_suffix(".lock.tmp")
        temp.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        os.replace(temp, marker)

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
