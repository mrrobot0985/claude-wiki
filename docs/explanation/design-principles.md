# Design Principles

Five invariants govern every change to this codebase.

______________________________________________________________________

## 1. Dependency Inversion

Core logic depends on Protocols, not concrete implementations. `ConfigManager` implements `RepoDetector` and `ConfigLoader`. `DefaultHookRegistrar` implements `HookRegistrar`. The CLI coordinates them but never imports their internals directly.

## 2. Single Responsibility

| Module          | Concern                        |
| --------------- | ------------------------------ |
| `interfaces.py` | Boundary contracts only        |
| `models.py`     | Immutable data, no behaviour   |
| `config.py`     | Path resolution and marker I/O |
| `factories.py`  | Single wiring point            |
| `cli.py`        | argparse UI                    |
| `hooks.py`      | Hook entry and dispatch        |

## 3. Stdlib First

- `argparse` for CLI, never Click
- `platformdirs` is the only non-stdlib path dependency
- No Jinja2 — Python dicts and dataclasses generate JSON directly

## 4. Testability

Protocols enable fakes. Tests for `ConfigManager` run in temp directories. Tests for `DefaultHookRegistrar` patch `HOME`. Integration tests inject fake command modules to verify the full lifecycle.

## 5. No Hardcoded Paths

Everything resolves at runtime via `.claude-wiki.lock`, environment variables, or XDG defaults. The same package works in any repository without recompilation.
