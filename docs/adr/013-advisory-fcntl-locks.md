# ADR-013: Concurrency — Repo-Level Advisory Locks

## Status

Accepted

## Context

The global registry already uses a bounded `fcntl` advisory lock
(`global_index.py:60-84`: `.lock` suffix, `LOCK_EX|LOCK_NB`, bounded retries →
`TimeoutError`, `finally` release). Two unguarded RMW cycles: daily-log append
(`flush.py:214-238` — two concurrent SessionEnd/PreCompact flushes can both read
`existing`, both append, second `os.replace` drops the first's entry) and
`state.json` update (`compile.py:373-438`).

## Decision

Add advisory `fcntl` locks only where concrete races exist, reusing
the `global_index.py:60-84` pattern:

1. **Daily-log append** — wrap `append_to_daily_log` (`flush.py:221-237`) with a
   per-repo lockfile `daily.log.lock` (in the machine-state dir).
1. **`state.json` RMW** — wrap the load-update-save sequence (`compile.py:373`→
   `438`) with `state_path.with_suffix(".json.lock")`.
1. **Per-repo compile serialization** — the `state.json` lock naturally serializes
   compiles for a given repo (every compile mutates `state.json`); different repos
   use different state files and stay parallel. No separate "compile lock."
1. Document: concurrent reads (query, status) are safe; concurrent writes
   serialize briefly. No queue, no lock-free, no SQLite, no lock server. `fcntl`
   is Unix-only; Windows gets a no-op stub (`sys.platform == "win32"` guard).

### Implementation guardrails (Honest)

document the **lack of write serialization
on Windows** explicitly in the README/status output — not just in code comments.
For a personal tool it's low risk, but be explicit.

## Consequences

Prevents the two concrete clobbering races; brief write
serialization acceptable for a personal tool; no new dependencies (stdlib
`fcntl`); Windows not serialized (documented).

## Alternatives rejected

SQLite registry/queue (DB + migration story for no
concrete failure); lock server (absurd for single-user); lock-free append-only
state (hypothetical scale problem).
