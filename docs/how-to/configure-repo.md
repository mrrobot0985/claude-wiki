# Configure a Repository

Control where knowledge lives and how it is compiled.

______________________________________________________________________

## The Marker File

`claude-wiki init` creates `.claude-wiki.lock` in the repository root:

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

## Override Knowledge Base Location

By default the compiled KB goes to an XDG directory:

```
~/.local/share/claude-wiki/<owner>/<repo>/
```

Set an environment variable to override:

```bash
export CLAUDE_WIKI_PROJECT_DIR=/mnt/fast-data/knowledge
claude-wiki compile
```

Or use an absolute path in `.claude-wiki.lock`:

```json
{
  "kb_dir": "/mnt/fast-data/knowledge"
}
```

## Moving Knowledge Base Data

If you change `kb_dir` or `daily_dir`, always run `migrate` so data is moved to the new location:

```bash
claude-wiki migrate --dry-run  # preview
claude-wiki migrate            # execute
```

The `migrate` command compares the current `.claude-wiki.lock` against `.claude-wiki.state.json` and moves directories only when paths differ.

## Global Registry

Every initialised repo is recorded in `~/.local/share/claude-wiki/index.md` — a machine-managed registry linking all your knowledge bases. It updates automatically on `init`, `compile`, and `migrate`.

## Hook Installation Scope

By default, `claude-wiki init` installs Claude Code hooks into the repo-local `.claude/settings.local.json`. This limits the blast radius to the current repository.

To install hooks globally (affecting all Claude Code sessions), use `--global`:

```bash
claude-wiki init --global
```

This writes to `~/.claude/settings.json` instead.

## Idempotent Reconfiguration

Re-run `claude-wiki init --force` to update the marker without duplicating hooks in the settings file.
