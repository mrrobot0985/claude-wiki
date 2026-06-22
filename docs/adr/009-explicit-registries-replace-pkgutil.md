# ADR-009: Replace `pkgutil` Auto-Discovery with Explicit Registries

## Status

Accepted

## Context

`cli.py:168-176` and `hooks.py:52-60` use `pkgutil.iter_modules` +
dynamic import and swallow any `Exception`, silently hiding broken modules. The
command/hook set is static; the extensibility seam is unused.

## Decision

Replace with explicit registries in `commands/__init__.py` and
`hook_handlers/__init__.py`, imported directly so import failures propagate
loudly. Brutal: "do this early — this is the soul of v1."

## Consequences

Fail-fast in CI; single source of truth for the command surface;
adding a command/hook requires editing the registry.

## Alternatives rejected

Keep `pkgutil` with narrower exception handling (still
hides real failures); entry-points plug-in mechanism (more indirection, zero
external consumers).
