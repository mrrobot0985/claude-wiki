# Architecture Overview

```
Conversation -> SessionEnd/PreCompact hooks -> flush.py
    -> daily/YYYY-MM-DD.md -> compile.py -> knowledge/
        -> SessionStart hook injects index.md -> cycle repeats
```

---

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

## Configuration Resolution

Priority chain for KB root (highest wins):

1. `CLAUDE_WIKI_PROJECT_DIR` env var
2. `.claude-wiki.json` with absolute `kb_dir`
3. XDG default: `~/.local/share/claude-wiki/<owner>/<repo>/`
4. Fallback: `~/.local/share/claude-wiki/local/<repo-name>/`

## Dependency Direction

Inner layers (`interfaces`, `models`, core logic) never import from outer layers (`cli`, `hooks`, `factories`). Factories wire concretions to protocols at application startup.
