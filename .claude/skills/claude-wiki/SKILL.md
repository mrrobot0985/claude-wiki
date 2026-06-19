---
name: claude-wiki
description: |-
  Bootstrap and manage the claude-wiki knowledge base for this repo.
  Covers init, shared rules, safety, and Makefile targets.
  For specific commands, invoke the dedicated /claude-wiki-<command> skills.
---

# claude-wiki

Knowledge base bootstrap and shared reference.

## Init

**Trigger**: "set up knowledge base", "init claude-wiki", "configure KB for this repo"

Run from the repo root after confirming it is a git repo.

1. Run `claude-wiki init`
1. By default hooks go into repo-local `.claude/settings.local.json`
1. If user wants user-wide hooks, add `--global` (writes to `~/.claude/settings.json`)
1. Completion: `.claude-wiki.lock` exists in repo root, repo appears in `~/.local/share/claude-wiki/core.md`

## Other Commands

Invoke the dedicated skill when needed:

- `/claude-wiki-compile` — compile daily logs into knowledge
- `/claude-wiki-query` — search and ask the knowledge base
- `/claude-wiki-lint` — run health checks on the KB
- `/claude-wiki-migrate` — move data when config paths change

## Rules

- Run from within the target repo root; `init`, `migrate`, and `compile` accept `--path <repo-root>`
- After any config edit to `kb_dir` or `daily_dir`, run `migrate --dry-run` before `migrate`
- Do not hand-edit `daily/` files — they are append-only
- Do not hand-edit `~/.local/share/claude-wiki/.registry.json` or `~/.local/share/claude-wiki/core.md` — they are machine-managed

## Safety

| Command         | Destructive?                   | Mitigation                                                        |
| --------------- | ------------------------------ | ----------------------------------------------------------------- |
| `init --force`  | Overwrites `.claude-wiki.lock` | Paths compared from the lock file itself; no secondary state file |
| `migrate`       | Moves directories              | `--dry-run` preview; warns and skips non-empty dest               |
| `compile --all` | Rebuilds entire KB             | Idempotent — recompiles from immutable daily                      |
| `lint`          | Read-only                      | None needed                                                       |

## Global Registry

Every `init`, `compile`, and `migrate` registers the repo in `~/.local/share/claude-wiki/core.md` and auto-evicts stale entries (repos whose `.claude-wiki.lock` has disappeared).

## Makefile Targets

```bash
make dev        # install with dev dependencies
make test       # run pytest
make lint       # ruff check
make format     # ruff format + mdformat
make typecheck  # mypy
make precommit  # all pre-commit hooks
make all        # full CI gate
make build      # build wheel
make clean      # remove artifacts
```

## Cost Reference

| Operation              | Approximate |
| ---------------------- | ----------- |
| compile one log        | $0.45–0.65  |
| query (no file-back)   | $0.15–0.25  |
| query (with file-back) | $0.25–0.40  |
| full lint (with LLM)   | $0.15–0.25  |
| structural lint only   | $0.00       |
