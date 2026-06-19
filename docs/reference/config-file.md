# Configuration File

`.claude-wiki.lock` — per-repository marker file. Machine-managed via `claude-wiki init` and `claude-wiki migrate`.

A companion file `.claude-wiki.state.json` is written automatically and tracks the last known configuration for change detection. Do not commit it — it is machine-managed.

______________________________________________________________________

## Schema

| Field                | Type                   | Default        | Description                |
| -------------------- | ---------------------- | -------------- | -------------------------- |
| `repo_name`          | `str`                  | directory name | Repository identifier      |
| `repo_owner`         | `str`                  | `"local"`      | Namespace for XDG path     |
| `kb_dir`             | `str` or absolute path | `"knowledge"`  | Knowledge base location    |
| `daily_dir`          | `str`                  | `"daily"`      | Source log directory       |
| `timezone`           | `str`                  | `"UTC"`        | Timezone for timestamps    |
| `compile_after_hour` | `int`                  | `18`           | Earliest auto-compile hour |

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
