# ADR-015: Keep `argparse`; Reject Typer/Click for v1

## Status

Accepted

## Context

The CLI problems are not `argparse` but `pkgutil` discovery
(ADR-009) and the completion generator's private `argparse` internals
(`_completions.py:35`, `argparse._SubParsersAction`).

## Decision

Keep `argparse` for v1. Reject Typer/Click. Isolate and guard the
private-API usage in `_completions.py`; covered by the existing drift-guard test.
Migration threshold (for the record): migrate only when (a) arg-handling drift
causes real bugs, (b) completion-generator pain recurs, or (c) rich
auto-documented option groups are needed.

### Implementation guardrails (Brutal)

if `_completions.py` private-API usage
hurts again post-v1, reconsider the generator (or migration) then — not now.
Correct call to keep argparse for v1.

## Consequences

Zero dependency cost; no migration churn; private-API use
isolated and guarded.

## Alternatives rejected

Typer (dependency + annotation boilerplate + churn);
Click (same cost, less ergonomics).
