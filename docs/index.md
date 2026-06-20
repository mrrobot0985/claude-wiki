# claude-wiki Documentation

Knowledge base system for Claude Code — installable Python package providing hooks and CLI.

______________________________________________________________________

## Getting Started

- [Quick Start Tutorial](tutorials/quickstart.md) — install and initialise your first repo

## Practical Guides

- [Install the Package](how-to/install.md) — pip, uv, or from source
- [Configure a Repository](how-to/configure-repo.md) — `.claude-wiki.lock` options, migration, and the global registry
- [Migrate to User Mode](how-to/migrate-project-to-user-mode.md) — move the KB out of the repo and into a central vault
- [Customise Hook Behaviour](how-to/customize-hooks.md) — event handlers and timeouts

## Understanding

- [Architecture Overview](explanation/architecture.md) — how the pieces fit together
- [Obsidian Graph Hygiene](explanation/obsidian-graph-hygiene.md) — keeping the graph readable at scale
- [Design Principles](explanation/design-principles.md) — why we made these choices

## Architecture Decision Records

- [ADR-001](adr/001-canonicalize-for-comparison.md) — Canonicalize for Comparison, Preserve for Identity
- [ADR-002](adr/002-best-effort-rollback-for-cross-filesystem.md) — Best-Effort Rollback for Cross-Filesystem Moves
- [ADR-003](adr/003-registry-as-reconciled-cache.md) — Registry as Reconciled Cache
- [ADR-004](adr/004-fail-fast-local-defensive-global.md) — Fail-Fast for Local State, Defensive for Global State
- [ADR-005](adr/005-kb-directory-redesign.md) — Knowledge Base Directory Redesign
- [ADR-006](adr/006-vault-naming-and-obsidian-graph-hygiene.md) — Vault Naming and Obsidian Graph Hygiene
- [ADR-007](adr/007-no-wikilinks-to-daily-logs.md) — No Wikilinks to Daily Logs

## Project Planning

- [Implementation Plan](plan.md) — completed ADR-006 execution plan and risk register

## Technical Reference

- [CLI Commands](reference/cli.md) — `claude-wiki` and `claude-wiki-hook`
- [Configuration File](reference/config-file.md) — `.claude-wiki.lock` schema
- [Data Models](reference/data-models.md) — `ProjectConfig` and results
- [Protocols](reference/protocols.md) — `RepoDetector`, `ConfigLoader`, etc.
- [Contributors Guide](reference/contributors.md) — development workflow
- [CI/CD Reference](reference/ci-cd.md) — GitHub Actions, SHA pinning, and PyPI trusted publishing
