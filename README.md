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
├── .claude-wiki.json            # per-repo config
├── daily/                     # conversation logs (commit these)
├── knowledge/                 # compiled articles (gitignored by default)
└── ~/.claude/settings.json    # global hook registration
```

## Configuration

`.claude-wiki.json` fields:

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
uv pip install -e . --group dev
uv run pytest
uvx ruff check .
uvx mypy --strict src tests
```
