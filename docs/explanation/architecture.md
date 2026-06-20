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

- `{repo_name}.md` — master catalog (read first by SessionStart)
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
- `~/.local/share/claude-wiki/core.md` — human-readable global catalog linking every repo's `{repo_name}.md`
- Updated automatically by `init`, `compile`, and `migrate`
- Injected into SessionStart context so the agent knows about other knowledge bases

## Configuration Resolution

Priority chain for KB root (highest wins):

1. `CLAUDE_WIKI_PROJECT_DIR` env var
1. Absolute `kb_dir` in `.claude-wiki.lock`
1. `kb_dir = "project"` → `<repo>/.claude/knowledge/` (default)
1. `kb_dir = "user"` → XDG: `~/.local/share/claude-wiki/<owner>/<repo>/`
1. Any other relative path → `<repo>/<path>/`

## State Tracking

- `.claude-wiki.lock` — per-repo config marker. `migrate` compares the previously saved config against the current config (including any `--kb-dir`, `--daily-dir`, or `--reports-dir` overrides) to detect path changes between runs.
- `state.json` — lives inside the knowledge base directory (`kb_root / state.json`) and tracks daily-log compilation hashes, timestamps, and cost estimates.
- Do not commit `state.json`; it is machine-managed.

## Dependency Direction

Inner layers (`interfaces`, `models`, core logic) never import from outer layers (`cli`, `hooks`, `factories`). Factories wire concretions to protocols at application startup.
