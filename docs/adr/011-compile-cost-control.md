# ADR-011: Compile Cost Control

## Status

Accepted

## Context

Compile includes the full index + all existing articles per log,
`max_turns=30`, no budget (`compile.py:186-279`). A 2-log run cost $7.79.
Incremental-by-hash + `--max-logs` exist but neither bounds prompt size or spend.
**Grounding:** `ResultMessage.total_cost_usd` is already consumed at
`compile.py:275-276`; `state.json` already tracks per-log `cost_usd`
(`compile.py:430`) and running `total_cost` (`compile.py:433`) — so the cap reuses
existing infrastructure.

## Decision

1. Existing-articles context budget: hardcode 15,000–25,000 chars.
1. Eviction: drop oldest first by recency + degree (hub articles with many
   wikilinks stay longer). The catalog/index is always included and does not
   count toward the budget.
1. Per-log USD cap: hardcode $0.50–$1.00 using `total_cost_usd`; above the cap, fail
   fast, mark the log failed for retry/manual review, log truncated-budget usage.
   Pre-call guard: reject obviously oversized prompts via `len(prompt)/4` token
   estimate before spending.
1. Model selection: capable model default; `--model`/`--cheap` opt-in only with
   an explicit quality warning.
1. Defaults hardcoded in v1 (hidden `--context-budget` only if users demand).
1. Schema-validate every LLM response before writing (see ADR-012).
1. No semantic determinism — verify structure, not semantic identity.
1. Document `compile --all` for periodic re-consolidation.

### Implementation guardrails (Brutal)

make the eviction heuristic **dead
simple** — recency plus a cheap hub-weight (reuse the existing inbound-link count
from `graph_utils`, do not compute graph degree fresh in the hot path). Hubs
staying longer is fine; do not overthink graph degree. A sort key like
`key = (is_hub, mtime)` is enough.

## Consequences

Bounded per-log cost; predictable bills; occasional weak distant
cross-links (recovered via index + periodic `compile --all`); cheaper model is an
explicit, warned opt-in.

## Alternatives rejected

Unbounded full context (cost cliff); cheaper model as
default (quality matters for a personal KB); user-configurable budget in v1 (UI
complexity before need); semantic determinism (research problem, not a product
fix).
