# Contributors Guide

Development workflow for the claude-wiki package.

______________________________________________________________________

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv pip install -e . --group dev
```

## Common Commands

```bash
# Run all tests
uv run pytest

# Run one test file
uv run pytest tests/test_config.py -v

# Type check
uvx mypy --strict src/

# Lint
uvx ruff check .

# Format
uvx ruff format .
```

## Adding a Command

1. Create `src/claude_wiki/commands/<name>.py`
1. Export `def register(subparsers, handlers) -> None: ...`
1. Add tests in `tests/test_<name>.py`

Commands are auto-discovered at runtime by `cli.py`.

## Adding a Hook Handler

1. Create `src/claude_wiki/hook_handlers/<event>.py`
1. Export `def register(handlers) -> None: ...`
1. Add tests in `tests/test_<event>.py`

Handlers are auto-discovered at runtime by `hooks.py`.

## Vertical Slices

Work is organised in end-to-end slices that cut through all layers. Each slice is a self-contained feature with tests.

| Slice | Feature                             |
| ----- | ----------------------------------- |
| 1     | `claude-wiki init`                  |
| 2     | `claude-wiki compile`               |
| 3     | `claude-wiki query`                 |
| 4     | `claude-wiki lint`                  |
| 5     | \`\`claude-wiki-hook SessionEnd\`   |
| 6     | \`\`claude-wiki-hook SessionStart\` |
| 7     | `claude-wiki-hook PreCompact`       |
| 8     | Package polish                      |

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: add session-start hook for capability detection
fix: handle empty stdin in standards-guard hook
chore(deps): bump actions/checkout from 4 to 6
```
