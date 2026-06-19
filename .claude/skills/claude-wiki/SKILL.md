---
name: claude-wiki
description: |-
  Orchestrate the claude-wiki knowledge base system.
  Use when the user wants to initialise a KB, compile daily logs into knowledge,
  query accumulated knowledge, run structural or full lint, or migrate data after
  config path changes.
---

# claude-wiki

Knowledge base lifecycle operations.

## Branches

### Bootstrap

**Trigger**: "set up knowledge base", "init claude-wiki", "configure KB for this repo"

Run from the repo root after confirming it is a git repo.

1. Run `claude-wiki init`
1. Completion: `.claude-wiki.lock` exists in repo root.

### Compile

**Trigger**: "compile today's logs", "build the KB", "sync knowledge"

1. Run `claude-wiki compile`
1. If user asks for full rebuild, add `--all`
1. Completion: `knowledge/index.md` reflects latest daily log.

### Query

**Trigger**: "search my KB", "what do I know about...", "ask the knowledge base"

1. Formulate the query as a single quoted string
1. Run `claude-wiki query "<question>"`
1. If user wants the answer saved back to KB, add `--file-back`
1. Completion: answer printed, and `--file-back` created `qa/` article and updated `index.md`.

### Lint

**Trigger**: "lint the knowledge base", "check KB health", "find broken links"

1. Run `claude-wiki lint`
1. For structural-only (no LLM cost), add `--structural-only`
1. Completion: report printed or report file path shown.

### Migrate

**Trigger**: "moved KB directory", "changed daily_dir", "migrate wiki data"

1. Run `claude-wiki migrate --dry-run` first
1. Review output — confirm paths and absence of errors
1. Run `claude-wiki migrate` to execute
1. Completion: `--dry-run` showed expected moves, actual run reported "State updated."

## Rules

- Always run from within the target repo root or pass `--path <repo-root>`
- After any config edit to `kb_dir` or `daily_dir`, run `migrate --dry-run` before `migrate`
- When `--dry-run` warns that destination exists, pause for human confirmation before overwriting
- Do not commit `.claude-wiki.state.json` — it is machine-managed
- Do not hand-edit `daily/` files — they are append-only

## Safety

| Command         | Destructive?                   | Mitigation                                   |
| --------------- | ------------------------------ | -------------------------------------------- |
| `init --force`  | Overwrites `.claude-wiki.lock` | Previous config backed up by `save_state`    |
| `migrate`       | Moves directories              | `--dry-run` preview; warns on non-empty dest |
| `compile --all` | Rebuilds entire KB             | Idempotent — recompiles from immutable daily |
| `lint`          | Read-only                      | None needed                                  |

## Cost Reference

| Operation              | Approximate |
| ---------------------- | ----------- |
| compile one log        | $0.45–0.65  |
| query (no file-back)   | $0.15–0.25  |
| query (with file-back) | $0.25–0.40  |
| full lint (with LLM)   | $0.15–0.25  |
| structural lint only   | $0.00       |
