# ADR-016: Reject MCP Server for In-Session KB Commands

## Status

Rejected (2026-06-22 — external review + anti-over-engineering rule)

## Context

The draft proposed a third entry point `claude-wiki-mcp` (stdio)
exposing read-only commands (`query`, `lint --structural-only`, `graph`,
`status`, `tags`, `registry list/show`) as typed, lazy-loaded MCP tools, keeping
mutating/expensive commands CLI-only. Today the non-hooks commands are invoked
via CLI or Claude Code skills (markdown prompts, always-in-context once loaded).

## Decision

Do **not** add an MCP server for v1.0. Keep the two-surface design:
hooks for capture, CLI for heavy/mutating/expensive ops, skills for read/query
guidance. `compile` and all mutating/expensive commands remain CLI/human-only
**permanently** — never model-invocable.

## Rationale

The proposal's benefits (typed schemas, lazy loading, structured
returns, no subprocess-per-call) were real but did not clear the bar of a
*concrete current failure* — skills work today and no user has reported
skill-prose cost as a problem. A long-running server process + `mcp` SDK
dependency surface + `.mcp.json` config + three-surface sync burden is not
justified for a single-user personal tool. The read-only/mutating boundary is
already enforced by simply not exposing mutating commands as skills. Brutal:
"Skill prompts are already good enough… strip, don't add." Making `compile`
model-invocable risks infinite loops and surprise bills.

## Alternatives considered

- (a) Full MCP server — rejected (this ADR).
- (b) Read-only MCP boundary only — rejected (same maintenance surface for
  marginal gain).
- (c) Slim existing skill markdown prompts without a new process — **defer.**
  Skills are already concise (40–55 lines); no measured context-cost problem. If
  one appears, trim `claude-wiki/SKILL.md` duplicated flag tables only; do not
  expand into a project.

## Consequences

Keep a simpler two-surface architecture; no new
process/dep/config. Forgo typed tool schemas and lazy loading for read-only ops.
Permanent boundary: `compile`/`init`/`migrate`/`rename-catalog`/`register`/
registry-cleanup never become skills or MCP tools.

## Closing note

The proposal was not wrong on the merits — typed MCP tools are
a better abstract interface than prose skill prompts — but premature for a
single-user tool with no measured failure. Revisit only if KB-scale skill-prompt
context cost becomes a measured problem, or a remote/multi-user surface is
genuinely needed.
