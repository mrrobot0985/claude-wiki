"""Immutable domain objects. No behaviour — plain data."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectConfig:
    """Per-repository configuration persisted in .claude-wiki.lock."""

    repo_name: str
    repo_owner: str = "local"
    kb_dir: Path = Path("project")
    daily_dir: Path = Path("daily")
    reports_dir: Path = Path("reports")
    timezone: str = "UTC"
    compile_after_hour: int = 18

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectConfig:
        """Hydrate from a JSON-compatible dict."""
        kwargs: dict[str, Any] = {}
        for f in dataclasses.fields(cls):
            val = data.get(f.name, f.default)
            if val is None:
                kwargs[f.name] = None
                continue
            if f.name in ("kb_dir", "daily_dir", "reports_dir"):
                kwargs[f.name] = Path(val) if not isinstance(val, Path) else val
            else:
                kwargs[f.name] = val
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        result: dict[str, Any] = {}
        for f in dataclasses.fields(self):
            val = getattr(self, f.name)
            if isinstance(val, Path):
                val = str(val)
            result[f.name] = val
        return result


@dataclass(frozen=True)
class CompileResult:
    files_processed: int
    articles_created: int
    articles_updated: int
    errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class QueryResult:
    answer: str
    citations: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class LintResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class FlushResult:
    concepts_extracted: int = 0
    connections_found: int = 0
    qa_filed: int = 0


@dataclass(frozen=True)
class MigrationResult:
    """Result of a config migration operation."""

    migrated: bool
    old_kb_dir: Path | None = None
    new_kb_dir: Path | None = None
    old_daily_dir: Path | None = None
    new_daily_dir: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
