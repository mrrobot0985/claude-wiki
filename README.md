# claude-wiki

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
claude-wiki compile
claude-wiki query "your question"
claude-wiki lint [--structural-only]
claude-wiki migrate [--dry-run]
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
└── daily/                         # conversation logs (created on first flush)
```

Use `claude-wiki init --global` to write hooks to `~/.claude/settings.json` instead.

## Configuration

`.claude-wiki.lock` fields:

```json
{
  "repo_name": "my-project",
  "repo_owner": "local",
  "kb_dir": "project",
  "daily_dir": "daily",
  "reports_dir": "reports",
  "timezone": "UTC",
  "compile_after_hour": 18
}
```

Set `CLAUDE_WIKI_PROJECT_DIR` to override the knowledge base location.

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
