# Architecture Overview

```
Conversation -> SessionEnd/PreCompact hooks -> flush.py
    -> daily/YYYY-MM-DD.md -> compile.py -> knowledge/
        -> SessionStart hook injects index.md -> cycle repeats
```

______________________________________________________________________

## Layer 1: Daily Logs (Source)

- Append-only, immutable after creation
- One file per day: `daily/YYYY-MM-DD.md`
- Captured automatically via hooks + `flush.py`
- Source of truth, committed to git

## Layer 2: Knowledge Base (Compiled)

- `index.md` — master catalog (read first by SessionStart)
- `concepts/` — one article per atomic piece of knowledge
- `connections/` — cross-cutting insights linking concepts
- `qa/` — filed query answers
- `log.md` — append-only build log

## Layer 3: Compilation

- `compile.py` reads daily logs, deduplicates, categorises
- `query.py` reads index, routes questions to relevant articles
- `lint.py` checks structural integrity and contradictions

## Layer 4: Global Registry

- `~/.local/share/claude-wiki/.registry.json` — machine-managed list of all repos
- `~/.local/share/claude-wiki/core.md` — human-readable global catalog linking every repo's `index.md`
- Updated automatically by `init`, `compile`, and `migrate`
- Injected into SessionStart context so the agent knows about other knowledge bases

## Configuration Resolution

Priority chain for KB root (highest wins):

1. `CLAUDE_WIKI_PROJECT_DIR` env var
1. `.claude-wiki.lock` with absolute `kb_dir`
1. XDG default: `~/.local/share/claude-wiki/<owner>/<repo>/`
1. Fallback: `~/.local/share/claude-wiki/local/<repo-name>/`

## State Tracking

- `.claude-wiki.state.json` — snapshot of the last known config in each repo root
- Used by `migrate` to detect path changes between runs
- Do not commit; it is machine-managed

## Dependency Direction

Inner layers (`interfaces`, `models`, core logic) never import from outer layers (`cli`, `hooks`, `factories`). Factories wire concretions to protocols at application startup.
