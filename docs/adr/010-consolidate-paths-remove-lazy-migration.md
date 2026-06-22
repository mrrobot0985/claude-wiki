# ADR-010: Consolidate Path Helpers; Remove Lazy Migration from `load()`

## Status

Accepted

## Context

`ConfigManager.load()` performs lazy layout migration as a side
effect of every config read (`config.py:103-214`, `_maybe_migrate_legacy`), with
LIFO rollback on partial failure. ADR-002 admits the cross-filesystem `st_dev`
pre-flight is documented but **not implemented**, and rollback reverses every
move unconditionally. Path logic is duplicated in `global_index._resolve_path` and
`status._check_daily`.

## Decision

1. `load()` becomes pure read + validate — no side effects.
1. On legacy layout, `load()` refuses with a loud actionable error: `Legacy layout detected. Run \`claude-wiki migrate\` to update paths.\`
1. `claude-wiki migrate` is the only migration path; it must be idempotent and
   safe.
1. Implement ADR-002's cross-filesystem pre-flight **inside `migrate`**: compare
   `os.stat(src).st_dev` vs `os.stat(dst.parent).st_dev`; same FS → proceed;
   different FS → emit a prominent, actionable warning and skip automatic
   rollback for that move.
1. Consolidate `global_index._resolve_path` and `status._check_daily` into
   `ConfigManager` helpers. Do **not** create a separate `PathResolver` class.

### Implementation guardrails (Honest)

the cross-FS warning must be prominent and
actionable, e.g. `"Cross-filesystem move detected. Manual verification of moved files recommended after completion."` — not a debug-level log.

## Consequences

Predictable, side-effect-free config loads; explicit one-time
user migration; safer cross-FS moves; one owner of path semantics. Tests relying
on implicit migration must call `migrate` explicitly.

## Alternatives rejected

Keep lazy migration in `load()` (least-surprise
violation); separate `PathResolver` class (over-engineering — `ConfigManager`
already owns paths).
