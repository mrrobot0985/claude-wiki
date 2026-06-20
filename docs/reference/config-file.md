# Configuration File

`.claude-wiki.lock` — per-repository marker file. Machine-managed via `claude-wiki init` and `claude-wiki migrate`.

The lock file itself serves as the migration checkpoint: `claude-wiki migrate` compares the previously saved config against the current config (including any CLI overrides) to detect path changes.

______________________________________________________________________

## Schema

| Field                | Type                           | Default                | Description                                              |
| -------------------- | ------------------------------ | ---------------------- | -------------------------------------------------------- |
| `repo_name`          | `str`                          | directory name         | Repository identifier                                    |
| `repo_owner`         | `str`                          | `"local"`              | Namespace for XDG path                                   |
| `kb_dir`             | `"project"`, `"user"`, or path | `"project"`            | KB location (see modes below)                            |
| `daily_dir`          | `str`                          | mode-aware (see below) | Source log directory                                     |
| `timezone`           | `str`                          | `"UTC"`                | IANA timezone for timestamps                             |
| `reports_dir`        | `str`                          | `"reports"`            | Deprecated and ignored; lint reports go to the cache dir |
| `compile_after_hour` | `int`                          | `18`                   | Earliest auto-compile hour                               |

## `kb_dir` Modes

| Mode                | Value         | Resolved path                                                                              |
| ------------------- | ------------- | ------------------------------------------------------------------------------------------ |
| `project` (default) | `"project"`   | `<repo>/.claude/knowledge/` — colocated with the repo, easy to gitignore or commit         |
| `user`              | `"user"`      | `~/.local/share/claude-wiki-vault/<owner>/<repo>/` — XDG directory, shared across machines |
| Custom relative     | `"my-kb"`     | `<repo>/my-kb/`                                                                            |
| Custom absolute     | `"/abs/path"` | Exact path                                                                                 |

`CLAUDE_WIKI_PROJECT_DIR` overrides any mode.

## `daily_dir` Defaults

A fresh `claude-wiki init` resolves `daily_dir` based on `kb_dir` mode (legacy locks that predate this keep an explicit `daily_dir` value):

| `kb_dir` mode | Default `daily_dir`                                |
| ------------- | -------------------------------------------------- |
| `project`     | `<repo>/.claude/daily`                             |
| `user`        | `~/.local/share/claude-wiki-daily/<owner>/<repo>/` |

`CLAUDE_WIKI_DAILY_DIR` overrides either default.

## Changing Paths

If you change `kb_dir` or `daily_dir`, run `claude-wiki migrate` to move existing data. Always preview with `--dry-run` first:

```bash
claude-wiki migrate --dry-run
claude-wiki migrate
```

## Timezone Validation

`timezone` is validated at load time against the IANA Time Zone Database. Values such as `"UTC"`, `"America/New_York"`, and `"Europe/Berlin"` are accepted. An invalid timezone raises a config error before any command runs:

```
ConfigError: timezone is not a valid IANA zone: Mars/Phobos
```

## Home Directory Expansion

`kb_dir`, `daily_dir`, and `reports_dir` values containing `~` are expanded to the user's home directory before path resolution. A value of `"~/wiki"` resolves to `/home/<user>/wiki` (or the equivalent on your platform) rather than creating a literal `~/wiki` directory under the repo root. This expansion applies both to `.claude-wiki.lock` values and to the `CLAUDE_WIKI_PROJECT_DIR`, `CLAUDE_WIKI_DAILY_DIR`, and `CLAUDE_WIKI_STATE_DIR` environment overrides.

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
