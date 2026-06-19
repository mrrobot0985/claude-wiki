# claude-wiki

Installable Python package providing Claude Code hooks and a CLI for a personal knowledge base.

## Install

From PyPI (recommended):

```bash
pip install claude-wiki
```

With `uv`:

```bash
uvx claude-wiki claude-wiki init
```

From source in a clone of this repo:

```bash
uv pip install -e .
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
```

Hook entry points (called by Claude Code via `~/.claude/settings.json`):

```bash
claude-wiki-hook SessionStart
claude-wiki-hook SessionEnd
claude-wiki-hook PreCompact
```

## What `claude-wiki init` creates

```text
my-project/
├── .claude-wiki.lock            # per-repo config (machine-managed)
├── daily/                     # conversation logs (commit these)
├── knowledge/                 # compiled articles (gitignored by default)
└── ~/.claude/settings.json    # global hook registration
```

## Configuration

`.claude-wiki.lock` fields:

```json
{
  "repo_name": "my-project",
  "repo_owner": "local",
  "kb_dir": "knowledge",
  "daily_dir": "daily",
  "timezone": "UTC",
  "compile_after_hour": 18
}
```

Set `CLAUDE_WIKI_PROJECT_DIR` to override the knowledge base location.

## Development

```bash
make dev        # install with dev dependencies
make test       # run pytest
make lint       # ruff check
make format     # ruff format + mdformat
make typecheck  # mypy
make precommit  # all pre-commit hooks
make all        # full CI gate (format, lint, typecheck, test, precommit)
```
