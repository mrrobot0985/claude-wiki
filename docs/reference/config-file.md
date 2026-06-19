# Configuration File

`.claude-wiki.json` — per-repository marker file.

---

## Schema

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `repo_name` | `str` | directory name | Repository identifier |
| `repo_owner` | `str` | `"local"` | Namespace for XDG path |
| `kb_dir` | `str` or absolute path | `"knowledge"` | Knowledge base location |
| `daily_dir` | `str` | `"daily"` | Source log directory |
| `timezone` | `str` | `"UTC"` | Timezone for timestamps |
| `compile_after_hour` | `int` | `18` | Earliest auto-compile hour |

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
