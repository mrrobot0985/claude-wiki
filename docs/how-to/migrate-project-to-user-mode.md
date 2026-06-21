# Migrate from Project Mode to User Mode

Move your knowledge base out of the repository and into a central vault.

______________________________________________________________________

## Why Migrate

Project mode stores the KB at `<repo>/.claude/knowledge/`. This works well for a single repository, but becomes awkward when:

- You want one Obsidian vault spanning many repos.
- You clone the repo frequently and do not want to recompile each time.
- You keep the repo in Dropbox / iCloud and the KB volume causes sync noise.

User mode relocates the KB to `~/.local/share/claude-wiki-vault/<owner>/<repo>/` (XDG-compliant, namespaced by owner). The daily log directory moves with it so everything stays together.

## Steps

### 1. Edit the Lock File

Open `.claude-wiki.lock` and change `kb_dir`:

```json
{
  "repo_name": "my-project",
  "repo_owner": "mrrobot0985",
  "layout_version": "2",
  "kb_dir": "user",
  "timezone": "UTC"
}
```

You only need to change `kb_dir` — `daily_dir` defaults to the same namespace automatically when omitted (it resolves to `~/.local/share/claude-wiki-daily/<owner>/<repo>/` in user mode). If you want to keep daily logs in the repo, set `"daily_dir": ".claude/daily"` explicitly.

### 2. Preview the Move

Run migrate with `--dry-run`:

```bash
claude-wiki migrate --dry-run
```

Output shows exactly which directories and files will be moved, created, or skipped. No data is touched.

### 3. Execute the Move

```bash
claude-wiki migrate
```

This performs three safe, idempotent actions:

1. **Moves KB data** from `.claude/knowledge/` to the user vault.
1. **Moves daily logs** if `daily_dir` changed.
1. **Rewrites wikilinks** so internal `[[links]]` remain valid after the directory move.

If a destination already exists, the move is skipped with a warning so nothing is overwritten.

### 4. Verify

```bash
claude-wiki status
```

All checks should show green. The catalog file is now `~/.local/share/claude-wiki-vault/mrrobot0985/my-project/my-project.md`.

### 5. Update Obsidian

If you were pointing an Obsidian vault at `<repo>/.claude/knowledge/`, repoint it to:

```
~/.local/share/claude-wiki-vault/
```

The global registry at `~/.local/share/claude-wiki-vault/core.md` updates automatically and now links to the user-mode KB.

## Rollback

If anything feels wrong, change `.claude-wiki.lock` back to `"kb_dir": "project"` and run `claude-wiki migrate` again. The tool moves data bidirectionally as long as the destination does not already exist.

## Gotchas

- **Absolute paths**: If you previously set `CLAUDE_WIKI_PROJECT_DIR` or `CLAUDE_WIKI_DAILY_DIR`, unset them before migrating so the lock file controls the layout.
- **Git tracking**: User-mode KBs and daily logs are outside the repo by design — they will never appear in `git status`.
- **Existing state**: `state.json` and `reports/` are relocated automatically; you do not need to move them manually.
