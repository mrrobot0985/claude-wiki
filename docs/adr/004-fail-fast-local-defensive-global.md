# ADR-004: Fail-Fast for Local State, Defensive for Global State

## Status

Accepted

## Context

The codebase has inconsistent error handling. Corrupt `.claude-wiki.lock` files raise raw `json.JSONDecodeError`; corrupt global registry silently erases all entries. Hook registration crashes with `AttributeError` on malformed `settings.json`. The user cannot predict whether a problem will be loud or silent.

## Decision

Adopt a **boundary-based** error-handling philosophy:

| Boundary                                         | Strategy                                                                                                                                                                                                                                                               | Rationale                                                                                                                                                        |
| ------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Repository-local (lock file, repo config, hooks) | **Fail-fast** with domain-specific exceptions (`ConfigError`). Migration returns a `MigrationResult` with `errors`/`warnings` rather than raising `MigrationError`. Hook registration writes JSON atomically; malformed settings are overwritten rather than crashing. | Local state is the user's responsibility; they must fix it before proceeding.                                                                                    |
| Machine-global (registry, global settings)       | **Defensive** recovery with warnings                                                                                                                                                                                                                                   | Global state may be affected by other processes, power loss, concurrent writes, or manual edits. The tool must degrade gracefully and preserve recoverable data. |

### Examples

- Corrupt `.claude-wiki.lock` → raise `ConfigError` with file path and original exception.
- Corrupt `.registry.json` → backup as `.registry.json.broken`, load valid entries, log warning.
- Missing hook script in `settings.json` → `DefaultHookRegistrar` overwrites known events with the current package command; no warning is emitted because the registrar is authoritative.

## Consequences

- **Positive:** Users get clear, actionable errors for problems they control.
- **Positive:** Global state corruption never crashes the tool; recovery is automatic.
- **Negative:** Two error-handling patterns to maintain; documentation and tests must be explicit about which boundary applies.
- **Negative:** Defensive global recovery can mask real bugs if warnings are ignored.

## Alternatives Rejected

- **Fail-fast everywhere** — a corrupt registry caused by another process would block all `claude-wiki` usage until manually fixed.
- **Defensive everywhere** — silently accepting a corrupt lock file would propagate nonsense paths downstream, causing data loss.
