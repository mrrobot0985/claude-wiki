# CLI Reference

## `claude-wiki`

User-facing commands.

```
usage: claude-wiki [-h] {init,migrate,compile,lint,query,rename-catalog} ...
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

| Option      | Description                               |
| ----------- | ----------------------------------------- |
| `--all`     | Force full recompile                      |
| `--file`    | Compile a specific daily log              |
| `--dry-run` | Show what would compile without writing   |
| `--path`    | Repo root (default: auto-detect from cwd) |

### `claude-wiki query`

Query the knowledge base.

```
claude-wiki query QUESTION [--file-back] [--path PATH] [--json] [--version]
```

| Option        | Description                                             |
| ------------- | ------------------------------------------------------- |
| `QUESTION`    | The question to ask                                     |
| `--file-back` | Save the answer to `knowledge/qa/`                      |
| `--path`      | Repo root (default: auto-detect from current directory) |
| `--json`      | Emit machine-readable JSON instead of human text        |
| `--version`   | Show `claude-wiki <version>` and exit                   |

JSON schema (`--json`):

```json
{
  "answer": "string",
  "citations": ["concepts/example"]
}
```

Confidence is omitted because the current implementation does not compute a meaningful score; emitting a fixed `0.0` would be misleading.

Exit codes:

| Code | Meaning                                   |
| ---- | ----------------------------------------- |
| `0`  | Answer produced                           |
| `1`  | Empty knowledge base / nothing to answer  |
| `2`  | Usage error or `claude-agent-sdk` missing |

Check the installed version:

```bash
claude-wiki query --version
```

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
| `--reports-dir` | Deprecated and ignored                         |

Use after editing `kb_dir` or `daily_dir` in `.claude-wiki.lock`. Always run `--dry-run` first.

### `claude-wiki lint`

Run health checks.

```
claude-wiki lint [--structural-only] [--fail-on-warning] [--path PATH] [--json] [--version]
```

| Option              | Description                                             |
| ------------------- | ------------------------------------------------------- |
| `--structural-only` | Skip LLM contradiction check                            |
| `--fail-on-warning` | Exit with status `1` when only warnings are present     |
| `--path`            | Repo root (default: auto-detect from current directory) |
| `--json`            | Emit machine-readable JSON instead of human text        |
| `--version`         | Show `claude-wiki <version>` and exit                   |

JSON schema (`--json`):

```json
{
  "issues": [
    {
      "severity": "error",
      "file": "concepts/example.md",
      "check": "broken_link",
      "message": "Broken link: [[missing-target]] - target does not exist"
    }
  ]
}
```

Exit codes:

| Code | Meaning                                                 |
| ---- | ------------------------------------------------------- |
| `0`  | Clean (or warnings present without `--fail-on-warning`) |
| `1`  | Warnings present and `--fail-on-warning` is passed      |
| `2`  | Errors present, or not inside a git repository          |

### `claude-wiki rename-catalog`

Rename a legacy `index.md` catalog to `{repo_name}.md` and rewrite article wikilinks that point to it (ADR-006).

```
claude-wiki rename-catalog [--dry-run] [--path PATH]
```

| Option      | Description                                  |
| ----------- | -------------------------------------------- |
| `--dry-run` | Show what would change without touching disk |
| `--path`    | KB root path (default: current repo's KB)    |

## `claude-wiki-hook`

Hook entry point called by Claude Code.

```
claude-wiki-hook SessionStart|SessionEnd|PreCompact
```

Reads session state from stdin, dispatches to registered handlers, and returns within the configured timeout.
