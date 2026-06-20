# CLI Reference

## `claude-wiki`

User-facing commands.

```text
usage: claude-wiki [-h] [--version]
                   {init,migrate,compile,lint,query,register,registry,rename-catalog,status,tags} ...
```

### Global options

| Option      | Description                           |
| ----------- | ------------------------------------- |
| `-h`        | Show help and exit                    |
| `--help`    | Show help and exit                    |
| `--version` | Show `claude-wiki <version>` and exit |

### `claude-wiki init`

Initialise KB for the current repository.

```text
usage: claude-wiki init [-h] [--path PATH] [--force] [--global] [--no-hooks]
                        [--kb-dir KB_DIR] [--daily-dir DAILY_DIR]
```

| Option             | Description                                              |
| ------------------ | -------------------------------------------------------- |
| `--path PATH`      | Repo root to initialise (default: auto-detect)           |
| `--force`          | Overwrite existing `.claude-wiki.lock`                   |
| `--global`         | Install hooks into `~/.claude/settings.json`             |
| `--no-hooks`       | Skip Claude Code hook installation                       |
| `--kb-dir KB_DIR`  | KB directory mode: `project`, `user`, or a custom path   |
| `--daily-dir PATH` | Daily log directory (default depends on `--kb-dir` mode) |

Creates `.claude-wiki.lock` and, unless `--no-hooks` is given, merges hooks into `.claude/settings.local.json` (or `~/.claude/settings.json` with `--global`).

### `claude-wiki compile`

Compile daily logs into the knowledge base.

```text
usage: claude-wiki compile [-h] [--all] [--file FILE] [--dry-run] [--path PATH]
```

| Option        | Description                                             |
| ------------- | ------------------------------------------------------- |
| `--all`       | Force recompile all daily logs                          |
| `--file FILE` | Compile a specific daily log file                       |
| `--dry-run`   | Show which logs would compile without writing           |
| `--path PATH` | Repo root (default: auto-detect from current directory) |

### `claude-wiki query`

Query the knowledge base.

```text
usage: claude-wiki query [-h] [--file-back] [--path PATH] [--json]
                         [--category {concepts,connections,qa}] [--tag TAG]
                         [--since SINCE] [--max-chars MAX_CHARS]
                         question
```

| Argument   | Description         |
| ---------- | ------------------- |
| `question` | The question to ask |

| Option                                   | Description                                                     |
| ---------------------------------------- | --------------------------------------------------------------- |
| `--file-back`                            | Save the answer to `knowledge/qa/`                              |
| `--path PATH`                            | Repo root (default: auto-detect from current directory)         |
| `--json`                                 | Emit machine-readable JSON instead of human text                |
| `--category {concepts\|connections\|qa}` | Restrict to a KB category (repeatable; union)                   |
| `--tag TAG`                              | Restrict to articles tagged `TAG` (repeatable; union)           |
| `--since SINCE`                          | Only articles updated/created on or after `YYYY-MM-DD`          |
| `--max-chars MAX_CHARS`                  | Cap article context; oldest articles dropped first (index kept) |

Scope filters compose by AND: `--category`, `--tag`, `--since`, and `--max-chars`
all apply together. An article without `updated`/`created` dates is always
included by `--since`. If no article matches the scope, the command prints a
clear message and exits `1`. Default (no scope flags) reads the whole KB.

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

### `claude-wiki lint`

Run health checks on the knowledge base.

```text
usage: claude-wiki lint [-h] [--structural-only] [--fail-on-warning]
                        [--path PATH] [--json] [--threshold THRESHOLD]
```

| Option              | Description                                             |
| ------------------- | ------------------------------------------------------- |
| `--structural-only` | Skip LLM-based contradiction checks                     |
| `--fail-on-warning` | Exit with status `1` when only warnings are present     |
| `--path PATH`       | Repo root (default: auto-detect from current directory) |
| `--json`            | Emit machine-readable JSON instead of human text        |
| `--threshold N`     | Sparse-article word threshold (default: `200`)          |

Checks include broken wikilinks, orphan pages, sparse articles (above the
threshold), required frontmatter fields (`frontmatter_missing_title`/`_sources`
are errors; `_aliases`/`_tags`/`_created`/`_updated` are warnings), and
single-use tags (`tag_single_use`, a suggestion). Suppress false positives with a
`.claude-wiki-lint-ignore` file at the repo root, one rule per line as
`path::check::reason` (paths support `fnmatch` globs); matched issues are dropped
from the report and the exit-code counts.

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

### `claude-wiki migrate`

Check and migrate data when config paths change.

```text
usage: claude-wiki migrate [-h] [--path PATH] [--dry-run] [--kb-dir KB_DIR]
                           [--daily-dir DAILY_DIR] [--reports-dir REPORTS_DIR]
```

| Option                      | Description                                    |
| --------------------------- | ---------------------------------------------- |
| `--path PATH`               | Repo root (default: auto-detect)               |
| `--dry-run`                 | Show what would move without touching disk     |
| `--kb-dir KB_DIR`           | Override knowledge base directory for this run |
| `--daily-dir DAILY_DIR`     | Override daily log directory for this run      |
| `--reports-dir REPORTS_DIR` | Deprecated and ignored                         |

Use after editing `kb_dir` or `daily_dir` in `.claude-wiki.lock`. Always run `--dry-run` first.

### `claude-wiki status`

Diagnose repository health.

```text
usage: claude-wiki status [-h] [--path PATH]
```

| Option        | Description                                             |
| ------------- | ------------------------------------------------------- |
| `--path PATH` | Repo root (default: auto-detect from current directory) |

### `claude-wiki tags`

List every YAML frontmatter tag in the knowledge base with a count and an
example article.

```text
usage: claude-wiki tags [-h] [--path PATH] [--json]
```

| Option        | Description                                             |
| ------------- | ------------------------------------------------------- |
| `--path PATH` | Repo root (default: auto-detect from current directory) |
| `--json`      | Emit machine-readable JSON instead of human text        |

Human output is aligned columns (`tag`, `count`, `example path`). With `--json`,
emits a list of objects `{"tag", "count", "examples": [...]}`. An empty
knowledge base prints a clear message and exits non-zero.

### `claude-wiki register`

Register an existing `.claude-wiki.lock` with the global KB index.

```text
usage: claude-wiki register [-h] [--path PATH]
```

| Option        | Description                                                     |
| ------------- | --------------------------------------------------------------- |
| `--path PATH` | Repo root containing `.claude-wiki.lock` (default: auto-detect) |

### `claude-wiki registry`

Manage the global knowledge-base registry.

```text
usage: claude-wiki registry [-h] {list,show,remove,clean} ...
```

| Subcommand | Description                          |
| ---------- | ------------------------------------ |
| `list`     | List every registered knowledge base |
| `show`     | Show details for a single repo       |
| `remove`   | Remove a repo from the registry      |
| `clean`    | Evict stale registry entries         |

#### `claude-wiki registry list`

```text
usage: claude-wiki registry list [-h]
```

No options besides `-h`/`--help`.

#### `claude-wiki registry show`

```text
usage: claude-wiki registry show [-h] repo
```

| Argument | Description                           |
| -------- | ------------------------------------- |
| `repo`   | Repository identifier as `owner/repo` |

#### `claude-wiki registry remove`

```text
usage: claude-wiki registry remove [-h] [--yes] repo
```

| Argument | Description                           |
| -------- | ------------------------------------- |
| `repo`   | Repository identifier as `owner/repo` |

| Option  | Description                  |
| ------- | ---------------------------- |
| `--yes` | Skip the confirmation prompt |

#### `claude-wiki registry clean`

```text
usage: claude-wiki registry clean [-h]
```

No options besides `-h`/`--help`.

### `claude-wiki rename-catalog`

Rename a legacy `index.md` catalog to `{repo_name}.md` and rewrite article wikilinks that point to it (ADR-006).

```text
usage: claude-wiki rename-catalog [-h] [--dry-run] [--path PATH]
```

| Option        | Description                                  |
| ------------- | -------------------------------------------- |
| `--dry-run`   | Show what would change without touching disk |
| `--path PATH` | KB root path (default: current repo's KB)    |

## `claude-wiki-hook`

Hook entry point called by Claude Code.

```text
usage: claude-wiki-hook SessionStart|SessionEnd|PreCompact
```

Reads session state from stdin, dispatches to registered handlers, and returns within the configured timeout.
