---
name: claude-wiki-dev
description: |
  Develop and maintain the claude-wiki package itself.
  Use when modifying CLI commands, hook handlers, migration logic, or adding new features.
  Covers project structure, testing patterns, and release workflow.
disable-model-invocation: true
---

# claude-wiki dev

Development reference for the claude-wiki package.

## Project Structure

```
src/claude_wiki/
  cli.py              # argparse main + subcommand dispatch
  config.py           # ConfigManager (repo detection, lock I/O, XDG resolution)
  factories.py        # DefaultConfigResolver wiring
  flush.py            # Shared context extraction + background flush logic
  global_index.py     # ~/.local/share/claude-wiki registry
  hooks.py            # Hook dispatcher (SessionStart, SessionEnd, PreCompact)
  migration.py        # MigrationManager (path change detection + data move)
  models.py           # Immutable dataclasses (ProjectConfig, MigrationResult, etc.)
  commands/           # Dynamically loaded subcommands
    compile.py
    lint.py
    query.py
  hook_handlers/      # Per-event handler modules
    session_start.py
    session_end.py
    pre_compact.py
tests/                # pytest suite
docs/                 # Documentation
.claude/skills/        # Claude Code skills for this repo
```

## Setup

```bash
make dev        # install package with dev deps (uv pip install -e ".[dev]")
```

Requires Python >=3.12.

## Development Cycle

```bash
make format     # ruff format + mdformat skills/docs
make lint       # ruff check
make typecheck  # mypy --strict src/
make test       # pytest
make test-cov   # pytest with coverage
make all        # format + lint + typecheck + test + precommit (full CI gate)
```

## Adding a New CLI Command

1. Create `src/claude_wiki/commands/<command>.py`
1. Implement `register(subparsers, handlers)` function
1. Optionally create `tests/test_<command>.py`
1. Optionally create `.claude/skills/claude-wiki-<command>/SKILL.md`
1. Register in `commands/__init__.py` (`_COMMAND_MODULES`) so `cli._register_commands()` loads it

## Hook Architecture

- `hooks.py` dispatches to handler modules by event name
- Each handler in `hook_handlers/` exports `handler(args) -> int` and `register(handlers: dict)`
- Handlers do fast local I/O only; heavy work is spawned to `flush.py` background process
- Recursion guard: `CLAUDE_INVOKED_BY` env var prevents nested hook triggers

## Testing Patterns

- Use `tempfile.TemporaryDirectory()` for CLI integration tests
- Use `tmp_path` pytest fixture for unit tests
- Patch `os.environ` for HOME/XDG overrides
- Mock `claude_wiki.cli.GlobalIndexManager` to avoid filesystem side effects
- Tests must be deterministic — no external network calls in tests

## Config & State

- `.claude-wiki.lock` is the single source of truth for repo config
- No secondary state file (`.claude-wiki.state.json` was removed)
- Migration compares current lock against previous by loading it as `previous`
- XDG data dir: `~/.local/share/claude-wiki/<owner>/<repo>/`

## Branching & CI

All changes go through a feature branch + PR. Never commit directly to `main`.

```bash
git checkout -b fix/short-description    # or feat/, chore/, docs/, refactor/
# ... work ...
git push -u origin fix/short-description
gh pr create --base main --title "fix: descriptive title" --body "..."
```

**CI gate** (must pass before merge):

1. `uv run pytest tests/ -v`
1. `uvx ruff check .`
1. `uvx ruff format --check .`
1. `uv run mypy src/`
1. `uvx --with mdformat-frontmatter --with mdformat-gfm mdformat --check ...`
1. Pre-commit hooks (`uv run pre-commit run --all-files`)

Verify with `make all` locally before pushing, then confirm `gh pr checks --watch` on the PR.

## Release

Version is tag-driven. Do **not** bump version in a PR.

**Current project setup** (static versioning in `pyproject.toml`):

1. Merge PR to `main`
1. Checkout `main`, pull latest
1. Edit `pyproject.toml` version
1. Commit: `chore: bump version to 0.x.y`
1. Tag: `git tag -a v0.x.y -m "Release v0.x.y"`
1. Push tag: `git push origin v0.x.y`
1. GitHub Actions builds and publishes to PyPI

**Industry recommendation** (SCM-derived versioning):
Use `hatch-vcs` or `setuptools-scm` so the version is derived from git tags automatically. This eliminates manual bump commits and merge conflicts.

```toml
[project]
dynamic = ["version"]

[tool.hatch.version]
source = "vcs"
```

With SCM-derived versioning, the workflow simplifies to: merge PRs → tag → release.

## Conventions

- **Commits**: conventional commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`)
- **Branches**: `feat/`, `fix/`, `chore/`, `docs/`, `refactor/`, `test/`, `ci/` prefix
- **Imports**: `from __future__ import annotations` at top; absolute imports preferred
- **Types**: `mypy --strict` required; annotate all public APIs
- **Formatting**: ruff format + mdformat with `mdformat-frontmatter` and `mdformat-gfm`
