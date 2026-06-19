---
name: claude-wiki-compile
description: Compile daily conversation logs into structured knowledge base articles. Invoke with /claude-wiki-compile.
disable-model-invocation: true
---

# claude-wiki compile

Turn immutable `daily/` logs into structured KB articles.

## Trigger

- "compile today's logs"
- "build the KB"
- "sync knowledge"
- "run compile"

## Process

1. Run `claude-wiki compile`
1. If user asks for full rebuild, add `--all`
1. If user wants one specific log, add `--file daily/YYYY-MM-DD.md`
1. If user wants a preview, add `--dry-run`
1. Completion: `knowledge/index.md` reflects latest daily log, global registry updated.

## Flags

| Flag            | Purpose                                       |
| --------------- | --------------------------------------------- |
| `--all`         | Force recompile entire KB from all daily logs |
| `--file <path>` | Compile a single daily log                    |
| `--dry-run`     | Preview what would compile without writing    |

## Rules

- Compilation is idempotent — re-running on the same log produces the same articles (deduplicated by hash)
- Do not hand-edit `daily/` files — they are append-only and the source of truth
- The KB lives under the XDG data dir by default (`~/.local/share/claude-wiki/<owner>/<repo>/`)

## Completion

- `knowledge/index.md` updated with new article links
- `knowledge/concepts/`, `connections/`, `qa/` populated or updated
- Global registry entry refreshed
