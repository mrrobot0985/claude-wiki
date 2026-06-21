# Data Models

All models are frozen dataclasses with no behaviour.

______________________________________________________________________

## `ProjectConfig`

```python
@dataclass(frozen=True)
class ProjectConfig:
    repo_name: str
    repo_owner: str = "local"
    layout_version: str = "2"
    kb_dir: Path = Path("project")
    daily_dir: Path = Path("daily")
    reports_dir: Path = Path("reports")
    timezone: str = "UTC"
    compile_after_hour: int = 18
```

Serialisation methods:

- `ProjectConfig.from_dict(data)` — hydrate from JSON
- `config.to_dict()` — emit JSON-compatible dict

## `CompileResult`

```python
@dataclass(frozen=True)
class CompileResult:
    files_processed: int
    articles_created: int
    articles_updated: int
    errors: list[str]
```

## `QueryResult`

```python
@dataclass(frozen=True)
class QueryResult:
    answer: str
    citations: list[str]
    confidence: float
```

## `LintResult`

```python
@dataclass(frozen=True)
class LintResult:
    errors: list[str]
    warnings: list[str]
    suggestions: list[str]
```

## `MigrationResult`

```python
@dataclass(frozen=True)
class MigrationResult:
    migrated: bool
    old_kb_dir: Path | None = None
    new_kb_dir: Path | None = None
    old_daily_dir: Path | None = None
    new_daily_dir: Path | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
```

Returned by `MigrationManager.check_and_migrate`. Indicates what moved and whether any warnings or errors occurred.

## `FlushResult`

```python
@dataclass(frozen=True)
class FlushResult:
    concepts_extracted: int
    connections_found: int
    qa_filed: int
```
