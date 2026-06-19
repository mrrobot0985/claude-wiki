# Protocols

All protocols are runtime-checkable. Inner layers depend on these, not concrete implementations.

______________________________________________________________________

## `RepoDetector`

```python
@runtime_checkable
class RepoDetector(Protocol):
    def find_repo_root(self, start: Path) -> Path: ...
```

Walks upward from `start` looking for `.git` or `.claude-wiki.lock`.

## `ConfigLoader`

```python
@runtime_checkable
class ConfigLoader(Protocol):
    def load(self, repo_root: Path) -> ProjectConfig: ...
    def write(self, repo_root: Path, config: ProjectConfig) -> None: ...
```

Reads and writes the repo-local `.claude-wiki.lock` marker file.

## `HookRegistrar`

```python
@runtime_checkable
class HookRegistrar(Protocol):
    def install_hooks(
        self,
        repo_root: Path,
        config: ProjectConfig,
        *,
        settings_path: Path,
    ) -> None: ...
```

Idempotently merges hook definitions into the given settings file path (`repo_root/.claude/settings.local.json` by default, or `~/.claude/settings.json` with `--global`).

## `Migrator`

```python
@runtime_checkable
class Migrator(Protocol):
    def check_and_migrate(
        self,
        repo_root: Path,
        current: ProjectConfig,
        previous: ProjectConfig | None,
        *,
        dry_run: bool = False,
    ) -> MigrationResult: ...
```

Detects path changes between config versions and moves data safely.

## Future Protocols (reserved)

- `KnowledgeCompiler` — `compile()`
- `QueryEngine` — `query()`
- `LintEngine` — `lint()`
- `FlushEngine` — `flush()`
