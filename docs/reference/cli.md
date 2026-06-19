# CLI Reference

## `claude-wiki`

User-facing commands.

```
usage: claude-wiki [-h] {init,migrate,compile,lint,query} ...
```

### `claude-wiki init`

Initialise KB for the current repository.

```
claude-wiki init [--path PATH] [--force] [--global]
```

| Option     | Description                                    |
| ---------- | ---------------------------------------------- |
| `--path`   | Repo root to initialise (default: auto-detect) |
| `--force`  | Overwrite existing `.claude-wiki.lock`         |
| `--global` | Install hooks into `~/.claude/settings.json`   |

Creates `.claude-wiki.lock` and merges hooks into `.claude/settings.local.json` (or `~/.claude/settings.json` with `--global`).

### `claude-wiki compile`

Compile daily logs into the knowledge base.

```
claude-wiki compile [--all] [--file FILE] [--dry-run] [--path PATH]
```

| Option      | Description                             |
| ----------- | --------------------------------------- |
| `--all`     | Force full recompile                    |
| `--file`    | Compile a specific daily log            |
| `--dry-run` | Show what would compile without writing |

### `claude-wiki query`

Query the knowledge base.

```
claude-wiki query QUESTION [--file-back]
```

| Option        | Description                        |
| ------------- | ---------------------------------- |
| `QUESTION`    | The question to ask                |
| `--file-back` | Save the answer to `knowledge/qa/` |

### `claude-wiki migrate`

Check and migrate data when config paths change.

```
claude-wiki migrate [--path PATH] [--dry-run] [--kb-dir PATH] [--daily-dir PATH] [--reports-dir PATH]
```

| Option          | Description                                    |
| --------------- | ---------------------------------------------- |
| `--path`        | Repo root to check (default: auto-detect)      |
| `--dry-run`     | Show what would move without touching disk     |
| `--kb-dir`      | Override knowledge base directory for this run |
| `--daily-dir`   | Override daily log directory for this run      |
| `--reports-dir` | Override lint reports directory for this run   |

Use after editing `kb_dir` or `daily_dir` in `.claude-wiki.lock`. Always run `--dry-run` first.

### `claude-wiki lint`

Run health checks.

```
claude-wiki lint [--structural-only]
```

| Option              | Description                  |
| ------------------- | ---------------------------- |
| `--structural-only` | Skip LLM contradiction check |

## `claude-wiki-hook`

Hook entry point called by Claude Code.

```
claude-wiki-hook SessionStart|SessionEnd|PreCompact
```

Reads session state from stdin, dispatches to registered handlers, and returns within the configured timeout.
