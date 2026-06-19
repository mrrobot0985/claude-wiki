---
name: claude-wiki-migrate
description: Migrate knowledge base data when config paths change. Invoke with /claude-wiki-migrate.
disable-model-invocation: true
---

# claude-wiki migrate

Move data when kb_dir, daily_dir, or reports_dir change.

## Trigger

- "moved KB directory"
- "changed daily_dir"
- "migrate wiki data"
- "change knowledge path"

## Process

1. Run claude-wiki migrate --dry-run first
1. Review output — confirm paths and absence of errors
1. Run claude-wiki migrate to execute
1. Completion: --dry-run showed expected moves; actual run reports "State updated." when paths changed, or "No migration needed — paths are unchanged."

## Flags

| Flag                   | Purpose                                       |
| ---------------------- | --------------------------------------------- |
| `--dry-run`            | Preview what would move without touching disk |
| `--kb-dir <path>`      | Override knowledge base directory             |
| `--daily-dir <path>`   | Override daily log directory                  |
| `--reports-dir <path>` | Override lint reports directory               |

## Rules

- --dry-run is mandatory before a real migration; review warnings carefully
- Migration refuses to proceed if new kb_dir and daily_dir would overlap
- If destination already exists and is not empty, the move is skipped with a warning
- After migration, .claude-wiki.lock is rewritten with the new paths
- The lock file itself serves as the previous-state reference; no secondary state file is maintained

## Completion

- Data moved from old paths to new paths (or skipped if destination occupied)
- .claude-wiki.lock updated with new directory paths
- Global registry updated if kb_dir changed
