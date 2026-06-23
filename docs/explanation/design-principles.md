# Design Principles

Five invariants govern every change to this codebase.

______________________________________________________________________

## 1. Dependency Inversion

Core logic coordinates concrete collaborators wired in `factories.py`. The CLI imports `ConfigManager`, `DefaultHookRegistrar`, and `MigrationManager` through `DefaultConfigResolver.build()` but never touches their internals directly.

## 2. Single Responsibility

| Module         | Concern                        |
| -------------- | ------------------------------ |
| `models.py`    | Immutable data, no behaviour   |
| `config.py`    | Path resolution and marker I/O |
| `factories.py` | Single wiring point            |
| `cli.py`       | argparse UI                    |
| `hooks.py`     | Hook entry and dispatch        |

## 3. Stdlib First

- `argparse` for CLI, never Click
- `platformdirs` is the only non-stdlib path dependency
- No Jinja2 — Python dicts and dataclasses generate JSON directly

## 4. Testability

Concrete classes are tested directly. Tests for `ConfigManager` run in temp directories. Tests for `DefaultHookRegistrar` patch `HOME`. Integration tests inject fake command modules to verify the full lifecycle.

## 5. No Hardcoded Paths

Everything resolves at runtime via `.claude-wiki.lock`, environment variables, or XDG defaults. The same package works in any repository without recompilation.
