# Protocols

All protocols are runtime-checkable. Inner layers depend on these, not concrete implementations.

---

## `RepoDetector`

```python
@runtime_checkable
class RepoDetector(Protocol):
    def find_repo_root(self, start: Path) -> Path: ...
```

Walks upward from `start` looking for `.git` or `.claude-wiki.json`.

## `ConfigLoader`

```python
@runtime_checkable
class ConfigLoader(Protocol):
    def load(self, repo_root: Path) -> ProjectConfig: ...
    def write(self, repo_root: Path, config: ProjectConfig) -> None: ...
```

Reads and writes the repo-local marker file.

## `HookRegistrar`

```python
@runtime_checkable
class HookRegistrar(Protocol):
    def install_hooks(self, repo_root: Path, config: ProjectConfig) -> None: ...
```

Idempotently merges hook definitions into `~/.claude/settings.json`.

## Future Protocols (reserved)

- `KnowledgeCompiler` — `compile()`
- `QueryEngine` — `query()`
- `LintEngine` — `lint()`
- `FlushEngine` — `flush()`
