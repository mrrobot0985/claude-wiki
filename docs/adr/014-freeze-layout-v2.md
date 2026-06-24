# ADR-014: Freeze Layout v2

## Status

Accepted

## Context

ADR-005/006/007 settled the v2 layout (vault-at-root, daily logs
outside the vault, XDG state/cache). Implemented across v0.3.0–v0.5.x. v1.0 needs
a stable structural baseline.

## Decision

Freeze v2 as the stable layout for v1.0. No new auto-migrations
post-v1. The legacy v1→v2 migration code was removed in v1.0.0 after the
grace period; only layout version "2" is accepted.

## Consequences

Users can script/backup against stable paths; no ongoing
multi-layout support obligation; v1 layouts are rejected and must be migrated
on a 0.x release before upgrading to v1.0.0.

## Alternatives rejected

Continue redesigning post-v1 (strands users/tooling);
keep auto-migrating indefinitely (accumulates debt).
