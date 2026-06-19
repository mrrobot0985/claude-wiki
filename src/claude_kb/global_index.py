"""Global registry — links all per-repo knowledge bases."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir


@dataclass
class RegistryEntry:
    """Single repo entry in the global registry."""

    repo_name: str
    repo_owner: str
    kb_root: str
    articles: int = 0
    last_compiled: str | None = None


class GlobalIndexManager:
    """Maintains a machine-managed registry and generates a human-readable global index."""

    _REGISTRY_NAME = ".registry.json"
    _INDEX_NAME = "index.md"

    def __init__(self, base_dir: Path | None = None) -> None:
        if base_dir is None:
            base_dir = Path(user_data_dir("claude-wiki", appauthor=False))
        self.base_dir = base_dir

    def _registry_path(self) -> Path:
        return self.base_dir / self._REGISTRY_NAME

    def _index_path(self) -> Path:
        return self.base_dir / self._INDEX_NAME

    def _ensure_base(self) -> None:
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _load_registry(self) -> list[RegistryEntry]:
        path = self._registry_path()
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return [RegistryEntry(**entry) for entry in data]
        except (json.JSONDecodeError, TypeError):
            return []

    def _save_registry(self, entries: list[RegistryEntry]) -> None:
        self._ensure_base()
        data = [asdict(e) for e in entries]
        self._registry_path().write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _generate_markdown(self, entries: list[RegistryEntry]) -> str:
        lines = ["# Global Knowledge Base Registry\n"]
        if not entries:
            lines.append("_No knowledge bases registered yet._\n")
        else:
            for e in sorted(entries, key=lambda x: (x.repo_owner, x.repo_name)):
                idx_link = Path(e.kb_root) / "index.md"
                compiled = e.last_compiled or "never"
                lines.append(
                    f"- **[{e.repo_owner}/{e.repo_name}]({idx_link})** — "
                    f"{e.articles} articles, last compiled {compiled}"
                )
            lines.append("")
        return "\n".join(lines)

    def register(
        self,
        repo_name: str,
        repo_owner: str,
        kb_root: Path,
        **kwargs: Any,
    ) -> None:
        """Upsert a registry entry. Preserves existing fields not overridden."""
        entries = self._load_registry()
        old = next(
            (
                e
                for e in entries
                if e.repo_name == repo_name and e.repo_owner == repo_owner
            ),
            None,
        )
        entries = [
            e
            for e in entries
            if not (e.repo_name == repo_name and e.repo_owner == repo_owner)
        ]

        new = old or RegistryEntry(
            repo_name=repo_name,
            repo_owner=repo_owner,
            kb_root=str(kb_root),
        )
        new.kb_root = str(kb_root)
        for k, v in kwargs.items():
            if hasattr(new, k):
                setattr(new, k, str(v) if isinstance(v, Path) else v)

        entries.append(new)
        self._save_registry(entries)
        self._index_path().write_text(self._generate_markdown(entries), encoding="utf-8")

    def unregister(self, repo_name: str, repo_owner: str) -> None:
        """Remove a repo from the global registry."""
        entries = self._load_registry()
        entries = [
            e
            for e in entries
            if not (e.repo_name == repo_name and e.repo_owner == repo_owner)
        ]
        self._save_registry(entries)
        self._index_path().write_text(self._generate_markdown(entries), encoding="utf-8")

    def list_entries(self) -> list[RegistryEntry]:
        """Return all registry entries, sorted by owner then name."""
        return sorted(self._load_registry(), key=lambda x: (x.repo_owner, x.repo_name))

    def compact_summary(
        self,
        exclude_repo_name: str | None = None,
        exclude_repo_owner: str | None = None,
    ) -> str:
        """Return a compact one-line summary of other registered KBs."""
        entries = self._load_registry()
        filtered = [
            e
            for e in entries
            if not (
                e.repo_name == exclude_repo_name
                and e.repo_owner == exclude_repo_owner
            )
        ]
        if not filtered:
            return ""
        parts = [
            f"{e.repo_name}({e.articles})"
            for e in sorted(filtered, key=lambda x: x.repo_name)
        ]
        return "Other KBs: " + ", ".join(parts)

    @staticmethod
    def count_articles(kb_root: Path) -> int:
        """Count compiled articles in a knowledge base."""
        subdirs = ("concepts", "connections", "qa")
        count = 0
        for sub in subdirs:
            subdir = kb_root / sub
            if subdir.exists():
                count += len(list(subdir.glob("*.md")))
        return count
