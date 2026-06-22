# ADR-008: Keep Hand-Rolled Dataclasses; Deduplicate Validation

## Status

Accepted

## Context

`ProjectConfig` is a frozen dataclass (`models.py:25-26`). Validation
is written twice: in `__post_init__` (`models.py:38-67`) and in `from_dict`
(`models.py:70-101`). The `object.__setattr__` in `__post_init__` is the standard
idiom for derived fields on a frozen dataclass and is tested. `pydantic` is on
disk only transitively (`claude-agent-sdk` → `mcp` → `pydantic`); adopting it would
add a declared dependency and a model-layer migration for a struct with \<12
fields.

## Decision

Keep frozen dataclasses. Reject Pydantic for v1. Consolidate
validation into one factory path (`from_dict`); `__post_init__` keeps only
invariants not expressible in the factory (timezone `ZoneInfo` check, `~`
expansion). Retain `object.__setattr__` for derived path fields.

### Implementation guardrails (Honest)

the factory path must exercise the **same
checks** as `__post_init__` (timezone, path expansion, `compile_after_hour`
range) to avoid divergence — exactly one validation path, not two
partially-overlapping ones.

## Consequences

No new declared dependency; single validation dialect; preserved
`expanduser` semantics. Remaining cost: hand-rolled validation, but the
duplicated tax is removed.

## Alternatives rejected

Adopt Pydantic v2 — "adds zero value here" (Brutal);
model-dumping quirks + serialization edge cases for a flat config struct.
