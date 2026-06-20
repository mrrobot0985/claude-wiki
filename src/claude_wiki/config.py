"""Configuration I/O and path resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_data_dir

from claude_wiki.errors import ConfigError, RepoNotFoundError
from claude_wiki.git_utils import infer_repo_owner
from claude_wiki.interfaces import ConfigLoader, RepoDetector
from claude_wiki.models import ProjectConfig


class ConfigManager(RepoDetector, ConfigLoader):
    """Concrete implementation: walks filesystem, resolves XDG paths."""

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
                "kb_dir": "project",
                "daily_dir": "daily",
                "reports_dir": "reports",
                "timezone": "UTC",
                "compile_after_hour": 18,
            }
            merged = {**defaults, **data}
            return ProjectConfig.from_dict(merged)
        # Infer from git remote, falling back to directory name + local owner.
        return ProjectConfig(
            repo_name=repo_root.name,
            repo_owner=infer_repo_owner(repo_root),
        )

    def write(self, repo_root: Path, config: ProjectConfig) -> None:
        """Persist .claude-wiki.lock atomically via a sibling temp file."""
        marker = repo_root / ".claude-wiki.lock"
        temp = marker.with_suffix(".lock.tmp")
        temp.write_text(json.dumps(config.to_dict(), indent=2), encoding="utf-8")
        os.replace(temp, marker)

    def get_kb_root(self, repo_root: Path, config: ProjectConfig) -> Path:
        """Resolve KB directory: env > absolute config > mode-based.

        Modes:
          - "user"    → XDG: ~/.local/share/claude-wiki/<owner>/<repo>/
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
            base = Path(user_data_dir("claude-wiki", appauthor=False))
            return (base / config.repo_owner / config.repo_name).resolve(strict=False)
        if kb_str == "project":
            return (repo_root / ".claude" / "knowledge").resolve(strict=False)

        # Fallback: relative path anchored at repo_root
        return (repo_root / kb_dir).resolve(strict=False)
