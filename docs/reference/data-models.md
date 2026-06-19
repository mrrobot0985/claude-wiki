# Data Models

All models are frozen dataclasses with no behaviour.

---

## `ProjectConfig`

```python
@dataclass(frozen=True)
class ProjectConfig:
    repo_name: str
    repo_owner: str = "local"
    kb_dir: Path = Path("knowledge")
    daily_dir: Path = Path("daily")
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

## `FlushResult`

```python
@dataclass(frozen=True)
class FlushResult:
    concepts_extracted: int
    connections_found: int
    qa_filed: int
```
