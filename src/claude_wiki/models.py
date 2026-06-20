"""Immutable domain objects. No behaviour — plain data."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_wiki.errors import ConfigError


def _field_default(f: dataclasses.Field) -> Any:  # type: ignore[type-arg]
    """Return the default value for a dataclass field."""
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:
        return f.default_factory()
    raise ConfigError(f"{f.name} is required")


@dataclass(frozen=True)
class ProjectConfig:
    """Per-repository configuration persisted in .claude-wiki.lock."""

    repo_name: str
    repo_owner: str = "local"
    kb_dir: Path = field(default_factory=lambda: Path("project"))
    daily_dir: Path = field(default_factory=lambda: Path("daily"))
    reports_dir: Path = field(default_factory=lambda: Path("reports"))
    timezone: str = "UTC"
    compile_after_hour: int = 18

    def __post_init__(self) -> None:
        """Validate all fields after construction."""
        for name in ("repo_name", "repo_owner", "timezone"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ConfigError(f"{name} must be a non-empty string")

        if (
            not isinstance(self.compile_after_hour, int)
            or not 0 <= self.compile_after_hour <= 23
        ):
            raise ConfigError("compile_after_hour must be an integer between 0 and 23")

        for name in ("kb_dir", "daily_dir", "reports_dir"):
            value = getattr(self, name)
            if not isinstance(value, (str, Path)):
                raise ConfigError(f"{name} must be a string or Path")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectConfig:
        """Hydrate from a JSON-compatible dict with strict validation."""
        required_from_dict = {"repo_name", "repo_owner", "compile_after_hour"}
        kwargs: dict[str, Any] = {}

        for f in dataclasses.fields(cls):
            if f.name in data:
                val = data[f.name]
                if val is None:
                    raise ConfigError(f"{f.name} cannot be null")
            elif f.name in required_from_dict:
                raise ConfigError(f"{f.name} is required")
            else:
                val = _field_default(f)

            if f.name in ("repo_name", "repo_owner", "timezone"):
                if not isinstance(val, str) or not val.strip():
                    raise ConfigError(f"{f.name} must be a non-empty string")
            elif f.name == "compile_after_hour":
                if not isinstance(val, int) or not 0 <= val <= 23:
                    raise ConfigError(
                        "compile_after_hour must be an integer between 0 and 23"
                    )
            elif f.name in ("kb_dir", "daily_dir", "reports_dir"):
                if isinstance(val, str):
                    val = Path(val)
                elif not isinstance(val, Path):
                    raise ConfigError(f"{f.name} must be a string or Path")

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
    rolled_back: list[tuple[str, Path, Path]] = field(default_factory=list)
