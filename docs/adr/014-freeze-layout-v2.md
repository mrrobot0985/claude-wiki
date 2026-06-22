# ADR-014: Freeze Layout v2

## Status

Accepted

## Context

ADR-005/006/007 settled the v2 layout (vault-at-root, daily logs
outside the vault, XDG state/cache). Implemented across v0.3.0–v0.5.x. v1.0 needs
a stable structural baseline.

## Decision

Freeze v2 as the stable layout for v1.0. No new auto-migrations
post-v1. The only active migration code is the v1→v2 path from ADR-005. After a
grace period, legacy v1 migration code may be removed.

## Consequences

Users can script/backup against stable paths; no ongoing
multi-layout support obligation; v1 migration code carried briefly post-v1.0.

## Alternatives rejected

Continue redesigning post-v1 (strands users/tooling);
keep auto-migrating indefinitely (accumulates debt).
