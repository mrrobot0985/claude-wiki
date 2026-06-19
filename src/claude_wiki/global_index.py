"""Global registry — links all per-repo knowledge bases."""

from __future__ import annotations

import fcntl
import json
import logging
import os
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from platformdirs import user_data_dir


logger = logging.getLogger(__name__)


@dataclass
class RegistryEntry:
    """Single repo entry in the global registry."""

    repo_name: str
    repo_owner: str
    kb_root: str
    articles: int = 0
    last_compiled: str | None = None
    repo_root: str | None = None


class GlobalIndexManager:
    """Maintains a machine-managed registry and generates a human-readable global core file."""

    _REGISTRY_NAME = ".registry.json"
    _INDEX_NAME = "core.md"
    _ALLOWED_FIELDS = {f.name for f in fields(RegistryEntry)}

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

    @contextmanager
    def _registry_lock(self) -> Iterator[None]:
        """Advisory lock protecting registry read-modify-write cycles."""
        lock_path = self._registry_path().with_suffix(".json.lock")
        self._ensure_base()
        with open(lock_path, "w") as lock_file:
            fcntl.lockf(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.lockf(lock_file.fileno(), fcntl.LOCK_UN)

    def _load_registry(self) -> list[RegistryEntry]:
        path = self._registry_path()
        if not path.exists():
            return []
        raw = path.read_text(encoding="utf-8")
        if not raw.strip():
            return []
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            self._backup_corrupt_registry(path)
            return []
        if not isinstance(data, list):
            self._backup_corrupt_registry(path)
            return []
        entries: list[RegistryEntry] = []
        skipped = False
        for item in data:
            try:
                entry = RegistryEntry(**item)
            except (TypeError, ValueError):
                skipped = True
                logger.warning("Skipping malformed registry entry: %s", item)
                continue
            for field in ("repo_root", "kb_root"):
                value = getattr(entry, field)
                if value is not None and not Path(value).is_absolute():
                    logger.warning(
                        "Registry entry %s/%s has relative %s; resolve before use",
                        entry.repo_owner,
                        entry.repo_name,
                        field,
                    )
            entries.append(entry)
        if skipped:
            self._backup_corrupt_registry(path)
        return entries

    def _backup_corrupt_registry(self, path: Path) -> None:
        backup = path.parent / f"{path.name}.{int(time.time())}.broken"
        try:
            path.rename(backup)
        except OSError:
            logger.exception("Failed to back up corrupt registry %s", path)
        else:
            logger.warning("Corrupt registry at %s backed up to %s", path, backup)

    def _save_registry(self, entries: list[RegistryEntry]) -> None:
        self._ensure_base()
        data = [asdict(e) for e in entries]
        path = self._registry_path()
        temp = path.parent / f".{path.name}.tmp.{os.getpid()}"
        temp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temp, path)

    def _validate_serializable(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            try:
                json.dumps(value)
            except (TypeError, ValueError) as e:
                raise ValueError(
                    f"Non-serializable value for registry field {key}: {value!r}"
                ) from e

    def _generate_markdown(self, entries: list[RegistryEntry]) -> str:
        lines = ["# Global Knowledge Base Registry\n"]
        if not entries:
            lines.append("_No knowledge bases registered yet._\n")
            return "\n".join(lines)
        for e in sorted(entries, key=lambda x: (x.repo_owner, x.repo_name)):
            kb_root = self._resolve_path(e.kb_root, e.repo_root)
            idx_link = self._format_link(kb_root / "index.md")
            compiled = e.last_compiled or "never"
            mode_suffix = ""
            if e.repo_root is not None:
                mode_label = self._derive_kb_mode_label(Path(e.repo_root))
                mode_suffix = f" *({mode_label})*"
            lines.append(f"## {e.repo_owner}/{e.repo_name}{mode_suffix}")
            lines.append(
                f"- **KB index:** [{e.repo_owner}/{e.repo_name}/index.md]({idx_link})"
            )
            if e.repo_root is not None:
                root_path = Path(e.repo_root)
                root_link = self._format_link(root_path)
                daily_dir = self._get_daily_dir(root_path)
                daily_link = self._format_link(daily_dir)
                lines.append(f"- **Repo root:** [{root_path.name}]({root_link})")
                lines.append(f"- **Daily logs:** [{daily_dir.name}]({daily_link})")
            lines.append(f"- **Articles:** {e.articles} | Last compiled: {compiled}")
            lines.append("")
        return "\n".join(lines)

    def _read_lock(self, repo_root: Path) -> dict[str, Any] | None:
        """Read .claude-wiki.lock at repo_root, returning None on missing/corrupt."""
        marker = repo_root / ".claude-wiki.lock"
        if not marker.exists():
            logger.warning(
                "Missing lock file at %s; using defaults",
                repo_root.resolve(strict=False),
            )
            return None
        try:
            data = json.loads(marker.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            logger.warning(
                "Corrupt lock file at %s: %s; using defaults",
                repo_root.resolve(strict=False),
                exc,
            )
            return None
        if not isinstance(data, dict):
            logger.warning(
                "Corrupt lock file at %s: expected object; using defaults",
                repo_root.resolve(strict=False),
            )
            return None
        return data

    def _get_daily_dir(self, repo_root: Path) -> Path:
        """Resolve the daily log directory for a repo root.

        Defaults to repo_root / "daily" when the lock file is missing or corrupt.
        """
        data = self._read_lock(repo_root)
        if data is None:
            return (repo_root / "daily").resolve(strict=False)
        daily = data.get("daily_dir", "daily")
        daily_path = Path(daily).expanduser()
        if daily_path.is_absolute():
            return daily_path.resolve(strict=False)
        return (repo_root / daily_path).resolve(strict=False)

    def _derive_kb_mode_label(self, repo_root: Path) -> str:
        """Return the human-readable KB mode label from the repo lock file."""
        data = self._read_lock(repo_root)
        kb_dir = str(data.get("kb_dir", "project")) if data else "project"
        if kb_dir == "user":
            return "user KB"
        if kb_dir == "project":
            return "project-local KB"
        return "custom KB"

    def _resolve_path(self, path_str: str, repo_root: str | None) -> Path:
        """Resolve a stored path to an absolute path.

        Relative paths are resolved against repo_root when available,
        otherwise against the current working directory for backwards compatibility.
        """
        path = Path(path_str)
        if path.is_absolute():
            return path
        if repo_root is not None:
            return (Path(repo_root) / path).resolve(strict=False)
        return path.resolve(strict=False)

    def _format_link(self, path: Path) -> str:
        """Format a path as an absolute markdown link target."""
        abs_path = path.resolve(strict=False)
        text = str(abs_path)
        if " " in text:
            return f"<{text}>"
        return text

    def sanitize(self) -> list[RegistryEntry]:
        """Evict entries whose repo root no longer contains a .claude-wiki.lock.

        Legacy entries (missing repo_root or relative repo_root) are preserved.
        Returns the evicted entries.
        """
        entries = self._load_registry()
        survivors: list[RegistryEntry] = []
        evicted: list[RegistryEntry] = []
        for e in entries:
            if e.repo_root is None:
                survivors.append(e)
                continue
            root_path = Path(e.repo_root)
            if not root_path.is_absolute():
                logger.warning(
                    "Preserving entry %s/%s with relative repo_root %s; "
                    "cannot determine repo health",
                    e.repo_owner,
                    e.repo_name,
                    e.repo_root,
                )
                survivors.append(e)
                continue
            root = root_path.resolve(strict=False)
            marker = root / ".claude-wiki.lock"
            if root.exists() and marker.exists():
                survivors.append(e)
            else:
                evicted.append(e)
        if evicted:
            with self._registry_lock():
                # Re-read under lock in case another process modified the registry.
                entries = self._load_registry()
                survivors = []
                evicted = []
                for e in entries:
                    if e.repo_root is None:
                        survivors.append(e)
                        continue
                    root_path = Path(e.repo_root)
                    if not root_path.is_absolute():
                        survivors.append(e)
                        continue
                    root = root_path.resolve(strict=False)
                    marker = root / ".claude-wiki.lock"
                    if root.exists() and marker.exists():
                        survivors.append(e)
                    else:
                        evicted.append(e)
                self._save_registry(survivors)
                self._index_path().write_text(
                    self._generate_markdown(survivors), encoding="utf-8"
                )
        return evicted

    def register(
        self,
        repo_name: str,
        repo_owner: str,
        kb_root: Path,
        *,
        repo_root: Path | None = None,
        **kwargs: Any,
    ) -> None:
        """Upsert a registry entry. Preserves existing fields not overridden.

        Also sanitizes the registry, evicting stale entries.
        """
        for key in kwargs:
            if key not in self._ALLOWED_FIELDS:
                raise ValueError(f"Unknown registry field: {key}")

        kb_root_abs = Path(kb_root).expanduser().resolve(strict=False)
        repo_root_abs = (
            Path(repo_root).expanduser().resolve(strict=False)
            if repo_root is not None
            else None
        )

        with self._registry_lock():
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
                kb_root=str(kb_root_abs),
            )
            new.kb_root = str(kb_root_abs)
            if repo_root_abs is not None:
                new.repo_root = str(repo_root_abs)
            for k, v in kwargs.items():
                setattr(new, k, str(v) if isinstance(v, Path) else v)

            self._validate_serializable(asdict(new))

            entries.append(new)
            self._save_registry(entries)
            self._index_path().write_text(
                self._generate_markdown(entries), encoding="utf-8"
            )

        self.sanitize()

    def unregister(self, repo_name: str, repo_owner: str) -> None:
        """Remove a repo from the global registry."""
        with self._registry_lock():
            entries = self._load_registry()
            entries = [
                e
                for e in entries
                if not (e.repo_name == repo_name and e.repo_owner == repo_owner)
            ]
            self._save_registry(entries)
            self._index_path().write_text(
                self._generate_markdown(entries), encoding="utf-8"
            )

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
                e.repo_name == exclude_repo_name and e.repo_owner == exclude_repo_owner
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
