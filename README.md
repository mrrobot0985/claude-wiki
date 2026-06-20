# claude-wiki

[![PyPI version](https://img.shields.io/pypi/v/claude-wiki)](https://pypi.org/project/claude-wiki/)
[![CI](https://img.shields.io/github/actions/workflow/status/mrrobot0985/claude-wiki/ci.yml?label=CI)](https://github.com/mrrobot0985/claude-wiki/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-wiki)](https://pypi.org/project/claude-wiki/)
[![License](https://img.shields.io/pypi/l/claude-wiki)](https://github.com/mrrobot0985/claude-wiki/blob/main/LICENSE)

Installable Python package providing Claude Code hooks and a CLI for a personal knowledge base.

## Install

With `uv` (recommended):

```bash
uvx claude-wiki init
```

From source in a clone of this repo:

```bash
uv sync --extra dev --frozen
```

## Usage

Initialize a repository:

```bash
claude-wiki init
```

Daily commands:

```bash
claude-wiki compile [--all] [--file FILE] [--dry-run] [--path PATH]
claude-wiki query "your question" [--file-back]
claude-wiki lint [--structural-only]
claude-wiki migrate [--dry-run] [--path PATH] [--kb-dir KB_DIR] [--daily-dir DAILY_DIR]
claude-wiki rename-catalog [--dry-run] [--path PATH]
```

Hook entry points (called by Claude Code via `.claude/settings.local.json` by default):

```bash
claude-wiki-hook SessionStart
claude-wiki-hook SessionEnd
claude-wiki-hook PreCompact
```

## What `claude-wiki init` creates

```text
my-project/
├── .claude-wiki.lock              # per-repo config (machine-managed)
├── .claude/settings.local.json   # repo-local hook registration (default)
└── .claude/daily/                 # conversation logs (created on first flush)
```

Use `claude-wiki init --global` to write hooks to `~/.claude/settings.json` instead.
Use `claude-wiki init --path PATH` to target a different repository root.

## Configuration

`.claude-wiki.lock` fields:

```json
{
  "repo_name": "my-project",
  "repo_owner": "local",
  "layout_version": "2",
  "kb_dir": "project",
  "daily_dir": ".claude/daily",
  "reports_dir": "reports",
  "timezone": "UTC",
  "compile_after_hour": 18
}
```

- `layout_version` tracks the internal directory-layout generation. New repositories use `"2"`.
- `daily_dir` defaults to `.claude/daily` in project mode and `~/.local/share/claude-wiki-daily/<owner>/<repo>/` in user mode.
- `reports_dir` is **deprecated**; reports are written to the cache directory (`<repo>/.claude/reports/` in project mode).

Set `CLAUDE_WIKI_PROJECT_DIR` to override the knowledge base location.

## Documentation

Full docs are in [`docs/`](docs/).

See [`examples/`](examples/) for a self-contained walkthrough of compiled output.

## Development

```bash
make dev              # install with dev dependencies
make install-precommit # install git hooks (run once per clone)
make test             # run pytest
make lint             # ruff check
make format           # ruff format + mdformat
make typecheck        # mypy
make precommit        # all pre-commit hooks
make all              # full CI gate (format, lint, typecheck, test, precommit)
```
