# ADR-003: Registry as Reconciled Cache

## Status

Proposed

> The reconcile behaviour described below is not yet implemented. The registry is written explicitly during `init`, `migrate`, and `compile` (via `GlobalIndexManager.register()`), but there is no automatic diff-and-reconcile step that compares the lock file with the stored registry entry. Manual lock-file edits can still leave stale registry entries until the next explicit register call.

## Context

The global registry (`~/.local/share/claude-wiki/.registry.json`) stores per-repo metadata such as `kb_root`, `repo_root`, and (proposed) `kb_mode`. It is populated during `init` and updated during `migrate`. If a user manually edits `.claude-wiki.lock` (e.g., changing `kb_dir`), the registry becomes stale. `core.md` then links to the wrong KB path, and `sanitize()` may evict the entry.

## Decision

Treat the registry as a **reconciled cache**, not an independent source of truth.

- The **lock file** (`.claude-wiki.lock`) is the sole source of truth for a repository's configuration.
- The **registry** is a machine-wide convenience index that is reconciled against the lock file whenever a command reads or writes the repository's state.
- `compile` calls `_maybe_reconcile_registry()` at the end of `_handle_compile()`, comparing the current lock file with the stored registry entry and updating `GlobalIndexManager` if `kb_dir`, `daily_dir`, `repo_owner`, or `repo_name` differ.
- `init` and `migrate` continue to register explicitly.
- The reconcile logic handles `repo_owner` changes by unregistering the old `(repo_owner, repo_name)` pair and registering the new one.

## Consequences

- **Positive:** Manual lock-file edits self-heal on the next compile; no separate `sync` command needed.
- **Positive:** `core.md` stays accurate without requiring users to remember an extra step.
- **Negative:** `compile` gains a side effect (registry mutation), making it not a pure function of daily logs → KB articles.
- **Negative:** Reconcile logic must handle edge cases such as missing `.claude-wiki.lock` (evict from registry) or missing `repo_root` directory (evict).

## Alternatives Rejected

- **Independent source of truth** — manual lock-file edits permanently desynchronize the two; user must run `migrate` for any config change, which is overkill for a path tweak.
- **Separate `sync` command** — users forget to run it; stale registry entries accumulate.
