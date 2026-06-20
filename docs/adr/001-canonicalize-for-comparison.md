# ADR-001: Canonicalize for Comparison, Preserve for Identity

## Status

Accepted

## Context

Multiple migration bugs (#12, #13) stem from path comparison: two logically identical paths (`/repo/.claude/knowledge` vs `/repo/../repo/.claude/knowledge`) compare as different, triggering false migrations. Meanwhile, symlink preservation is a real user concern — a developer may symlink `.claude` to a faster disk or a shared workspace.

## Decision

We will maintain **two representations** of every managed path:

1. **Canonical path** — `Path.resolve(strict=False)`, used for equality checks, overlap detection, and validation. This is the path that determines whether two configs refer to the same directory.
1. **Display path** — the original string from the lock file or user input, stored in `.claude-wiki.lock` and shown in CLI output. This preserves symlinks and relative segments as the user wrote them.

`ConfigManager.get_kb_root()` returns the **canonical path**. Callers that need the display path read it from `ProjectConfig` directly.

## Consequences

- **Positive:** False migrations from `..` or symlink indirection are eliminated.
- **Positive:** Users see the paths they configured, not resolved system paths.
- **Negative:** Internal code must be explicit about which representation it uses. Mixing them up reintroduces bugs.
- **Negative:** Migration result objects (`MigrationResult`) carry canonical resolved paths (`old_kb_dir`, `new_kb_dir`, etc.). Display paths are read from `ProjectConfig` directly when needed for CLI output.

## Alternatives Rejected

- **Always resolve** — breaks intentional symlinks; user reports `.claude` is a symlink to `/mnt/fast` and `resolve()` stores the real path, confusing them.
- **Always preserve** — `/repo/../repo/.claude/knowledge` and `/repo/.claude/knowledge` compare different, false migrations persist.
- **Store only canonical** — lock file becomes unreadable; users can't predict where their KB will land.
