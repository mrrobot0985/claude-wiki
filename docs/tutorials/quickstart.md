# Quick Start

Get a knowledge base running in your repository in under five minutes.

______________________________________________________________________

## Prerequisites

- Python 3.12+
- A git repository

## Step 1: Install

```bash
uvx claude-wiki claude-wiki init
```

Or with pip:

```bash
pip install claude-wiki
```

## Step 2: Initialise Your Repository

```bash
cd my-project
claude-wiki init
```

This creates three things:

1. `.claude-wiki.lock` — per-repo configuration
1. `daily/` — conversation logs (commit these)
1. `~/.claude/settings.json` — global hook registration for Claude Code

## Step 3: Use Your Knowledge Base

After a few conversations, compile captured knowledge:

```bash
claude-wiki compile
```

Ask questions against the compiled index:

```bash
claude-wiki query "how does the config system work?"
```

Run health checks:

```bash
claude-wiki lint
```

## Cross-Repository Awareness

If you have multiple repos with claude-wiki, `~/.local/share/claude-wiki/index.md` links them all. The `SessionStart` hook shows a compact summary of other knowledge bases alongside the current repo's index.

## Moving Data Safely

If you change `kb_dir` or `daily_dir`, migrate the data:

```bash
claude-wiki migrate --dry-run
claude-wiki migrate
```

______________________________________________________________________

That's it. The hooks fire automatically via Claude Code's `SessionStart`, `SessionEnd`, and `PreCompact` events.
