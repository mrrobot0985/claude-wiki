# Configure a Repository

Control where knowledge lives and how it is compiled.

______________________________________________________________________

## The Marker File

`claude-wiki init` creates `.claude-wiki.lock` in the repository root:

```json
{
  "repo_name": "my-project",
  "repo_owner": "local",
  "kb_dir": "project",
  "daily_dir": "daily",
  "reports_dir": "reports",
  "timezone": "UTC",
  "compile_after_hour": 18
}
```

## Knowledge Base Location Modes

`kb_dir` supports three modes:

| Mode                | Value                      | Resolved path                                |
| ------------------- | -------------------------- | -------------------------------------------- |
| `project` (default) | `"project"`                | `<repo>/.claude/knowledge/`                  |
| `user`              | `"user"`                   | `~/.local/share/claude-wiki/<owner>/<repo>/` |
| Custom              | `"my-kb"` or `"/abs/path"` | `<repo>/my-kb/` or exact path                |

Set an environment variable to override everything:

```bash
export CLAUDE_WIKI_PROJECT_DIR=/mnt/fast-data/knowledge
claude-wiki compile
```

## Moving Knowledge Base Data

If you change `kb_dir` or `daily_dir`, always run `migrate` so data is moved to the new location:

```bash
claude-wiki migrate --dry-run  # preview
claude-wiki migrate            # execute
```

The `migrate` command detects changes between the previous and current `.claude-wiki.lock` configurations (including any `--kb-dir`, `--daily-dir`, or `--reports-dir` overrides) and safely moves data to the new locations.

## Global Registry

Every initialised repo is recorded in `~/.local/share/claude-wiki/core.md` — a machine-managed registry linking all your knowledge bases. It updates automatically on `init`, `compile`, and `migrate`.

## Hook Installation Scope

By default, `claude-wiki init` installs Claude Code hooks into the repo-local `.claude/settings.local.json`. This limits the blast radius to the current repository.

To install hooks globally (affecting all Claude Code sessions), use `--global`:

```bash
claude-wiki init --global
```

This writes to `~/.claude/settings.json` instead.

## Idempotent Reconfiguration

Re-run `claude-wiki init --force` to update the marker without duplicating hooks in the settings file.
