"""Configuration I/O and path resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_data_dir

from claude_kb.errors import RepoNotFoundError
from claude_kb.interfaces import ConfigLoader, RepoDetector
from claude_kb.models import ProjectConfig


class ConfigManager(RepoDetector, ConfigLoader):
    """Concrete implementation: walks filesystem, resolves XDG paths."""

    _STATE_NAME = ".claude-wiki.state.json"

    def find_repo_root(self, start: Path) -> Path:
        """Walk upward looking for .git or .claude-wiki.json."""
        current = start.resolve()
        while True:
            if (current / ".git").exists() or (current / ".claude-wiki.json").exists():
                return current
            parent = current.parent
            if parent == current:
                raise RepoNotFoundError(
                    f"Not in a git repo: no .git or .claude-wiki.json found from {start}"
                )
            current = parent

    def load(self, repo_root: Path) -> ProjectConfig:
        """Read .claude-wiki.json if present, else infer defaults."""
        marker = repo_root / ".claude-wiki.json"
        if marker.exists():
            data = json.loads(marker.read_text())
            return ProjectConfig.from_dict(data)
        # Infer from directory name
        return ProjectConfig(
            repo_name=repo_root.name,
            repo_owner="local",
        )

    def write(self, repo_root: Path, config: ProjectConfig) -> None:
        """Persist .claude-wiki.json."""
        marker = repo_root / ".claude-wiki.json"
        marker.write_text(json.dumps(config.to_dict(), indent=2))

    def get_kb_root(self, config: ProjectConfig) -> Path:
        """Resolve KB directory: env > absolute config > XDG."""
        # Priority 1: environment override
        env_dir = os.environ.get("CLAUDE_WIKI_PROJECT_DIR")
        if env_dir:
            return Path(env_dir)

        # Priority 2: absolute path in config
        if config.kb_dir.is_absolute():
            return config.kb_dir

        # Priority 3: XDG default
        base = Path(user_data_dir("claude-wiki", appauthor=False))
        return base / config.repo_owner / config.repo_name

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
