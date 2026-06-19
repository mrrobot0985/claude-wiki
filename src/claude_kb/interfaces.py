"""Boundary protocols. Core logic depends on these, not concretions."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from claude_kb.models import MigrationResult, ProjectConfig


@runtime_checkable
class RepoDetector(Protocol):
    """Finds the repository root from any starting directory."""

    def find_repo_root(self, start: Path) -> Path: ...


@runtime_checkable
class ConfigLoader(Protocol):
    """Reads and writes the repo-local .claude-wiki.json marker."""

    def load(self, repo_root: Path) -> ProjectConfig: ...
    def write(self, repo_root: Path, config: ProjectConfig) -> None: ...
    def save_state(self, repo_root: Path, config: ProjectConfig) -> None: ...
    def load_state(self, repo_root: Path) -> ProjectConfig | None: ...


@runtime_checkable
class HookRegistrar(Protocol):
    """Mutates the global ~/.claude/settings.json to register hooks."""

    def install_hooks(self, repo_root: Path, config: ProjectConfig) -> None: ...


@runtime_checkable
class Migrator(Protocol):
    """Detects and executes migration when config paths change."""

    def check_and_migrate(
        self,
        repo_root: Path,
        current: ProjectConfig,
        previous: ProjectConfig | None,
        *,
        dry_run: bool = False,
    ) -> MigrationResult: ...
    def save_state(self, repo_root: Path, config: ProjectConfig) -> None: ...
    def load_state(self, repo_root: Path) -> ProjectConfig | None: ...
