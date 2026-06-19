# Configure a Repository

Control where knowledge lives and how it is compiled.

---

## The Marker File

`claude-wiki init` creates `.claude-wiki.json` in the repository root:

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

Or use an absolute path in `.claude-wiki.json`:

```json
{
  "kb_dir": "/mnt/fast-data/knowledge"
}
```

## Idempotent Reconfiguration

Re-run `claude-wiki init --force` to update the marker without duplicating hooks in `settings.json`.
