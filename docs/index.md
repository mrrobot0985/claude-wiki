# claude-wiki Documentation

Knowledge base system for Claude Code — installable Python package providing hooks and CLI.

______________________________________________________________________

## Getting Started

- [Quick Start Tutorial](tutorials/quickstart.md) — install and initialise your first repo

## Practical Guides

- [Install the Package](how-to/install.md) — pip, uv, or from source
- [Configure a Repository](how-to/configure-repo.md) — `.claude-wiki.lock` options, migration, and the global registry
- [Customise Hook Behaviour](how-to/customize-hooks.md) — event handlers and timeouts

## Understanding

- [Architecture Overview](explanation/architecture.md) — how the pieces fit together
- [Design Principles](explanation/design-principles.md) — why we made these choices

## Technical Reference

- [CLI Commands](reference/cli.md) — `claude-wiki` and `claude-wiki-hook`
- [Configuration File](reference/config-file.md) — `.claude-wiki.lock` schema
- [Data Models](reference/data-models.md) — `ProjectConfig` and results
- [Protocols](reference/protocols.md) — `RepoDetector`, `ConfigLoader`, etc.
- [Contributors Guide](reference/contributors.md) — development workflow
