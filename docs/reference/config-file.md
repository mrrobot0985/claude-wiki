# Configuration File

`.claude-wiki.lock` — per-repository marker file. Machine-managed via `claude-wiki init` and `claude-wiki migrate`.

The lock file itself serves as the migration checkpoint: `claude-wiki migrate` compares the previously saved config against the current config (including any CLI overrides) to detect path changes.

______________________________________________________________________

## Schema

| Field                | Type                           | Default        | Description                   |
| -------------------- | ------------------------------ | -------------- | ----------------------------- |
| `repo_name`          | `str`                          | directory name | Repository identifier         |
| `repo_owner`         | `str`                          | `"local"`      | Namespace for XDG path        |
| `kb_dir`             | `"project"`, `"user"`, or path | `"project"`    | KB location (see modes below) |
| `daily_dir`          | `str`                          | `"daily"`      | Source log directory          |
| `timezone`           | `str`                          | `"UTC"`        | Timezone for timestamps       |
| `reports_dir`        | `str`                          | `"reports"`    | Lint report directory         |
| `compile_after_hour` | `int`                          | `18`           | Earliest auto-compile hour    |

## `kb_dir` Modes

| Mode                | Value         | Resolved path                                                                        |
| ------------------- | ------------- | ------------------------------------------------------------------------------------ |
| `project` (default) | `"project"`   | `<repo>/.claude/knowledge/` — colocated with the repo, easy to gitignore or commit   |
| `user`              | `"user"`      | `~/.local/share/claude-wiki/<owner>/<repo>/` — XDG directory, shared across machines |
| Custom relative     | `"my-kb"`     | `<repo>/my-kb/`                                                                      |
| Custom absolute     | `"/abs/path"` | Exact path                                                                           |

`CLAUDE_WIKI_PROJECT_DIR` overrides any mode.

## Changing Paths

If you change `kb_dir` or `daily_dir`, run `claude-wiki migrate` to move existing data. Always preview with `--dry-run` first:

```bash
claude-wiki migrate --dry-run
claude-wiki migrate
```

## Examples

### In-repo knowledge base (gitignored)

```json
{
  "repo_name": "my-project",
  "kb_dir": "knowledge"
}
```

### External knowledge base

```json
{
  "repo_name": "my-project",
  "kb_dir": "/mnt/fast-data/knowledge"
}
```

### Custom daily log directory

```json
{
  "repo_name": "my-project",
  "daily_dir": "logs/conversations"
}
```
