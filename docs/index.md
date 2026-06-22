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
- [Use Tags](how-to/use-tags.md) — add tags, query by tag, and interpret `tag_single_use` suggestions
- [Install Shell Completions and the Man Page](how-to/install-shell-completions.md) — bash, zsh, fish, and `man claude-wiki`
- [Suppress Lint False Positives](how-to/suppress-lint-false-positives.md) — `.claude-wiki-lint-ignore` rules and fnmatch globs
- [Use JSON Output in CI and Scripts](how-to/use-json-output.md) — `query --json` and `lint --json` schemas plus exit codes
- [Scope Queries](how-to/scope-queries.md) — category, date, tag, and context filters
- [Inspect KB Topology with `graph`](how-to/use-graph.md) — orphans, hubs, and fragmentation at a glance
- [Upgrade to v1.0](how-to/upgrade-to-v1.md) — 0.x to stable release checklist

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
- [ADR-008](adr/008-keep-dataclasses-dedupe-validation.md) — Keep Hand-Rolled Dataclasses; Deduplicate Validation
- [ADR-009](adr/009-explicit-registries-replace-pkgutil.md) — Replace `pkgutil` Auto-Discovery with Explicit Registries
- [ADR-010](adr/010-consolidate-paths-remove-lazy-migration.md) — Consolidate Path Helpers; Remove Lazy Migration from `load()`
- [ADR-011](adr/011-compile-cost-control.md) — Compile Cost Control
- [ADR-012](adr/012-constrained-write-schema.md) — Drop `acceptEdits` for a Constrained Write Schema
- [ADR-013](adr/013-advisory-fcntl-locks.md) — Concurrency — Repo-Level Advisory Locks
- [ADR-014](adr/014-freeze-layout-v2.md) — Freeze Layout v2
- [ADR-015](adr/015-keep-argparse.md) — Keep `argparse`; Reject Typer/Click for v1
- [ADR-016](adr/016-reject-mcp-server.md) — Reject MCP Server for In-Session KB Commands (Rejected)

## Project Planning

- [Implementation Plan](plan.md) — road to v1.0: status, what's done, what remains

## Community

- [Code of Conduct](/CODE_OF_CONDUCT.md) — Contributor Covenant 2.1
- [Security Policy](/SECURITY.md) — supported versions and vulnerability reporting
- [Contributors Guide](/CONTRIBUTING.md) — development workflow and conventions

## Technical Reference

- [Stability Policy](reference/stability.md) — SemVer guarantees and experimental surfaces
- [CLI Commands](reference/cli.md) — `claude-wiki` and `claude-wiki-hook`
- [Configuration File](reference/config-file.md) — `.claude-wiki.lock` schema
- [Data Models](reference/data-models.md) — `ProjectConfig` and results
- [Protocols](reference/protocols.md) — `RepoDetector`, `ConfigLoader`, etc.
- [Contributors Guide](reference/contributors.md) — development workflow
- [CI/CD Reference](reference/ci-cd.md) — GitHub Actions, SHA pinning, and PyPI trusted publishing
