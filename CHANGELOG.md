# Changelog

All notable changes to this project are documented in this file.

## [unreleased]

### Added

- Claude-wiki knowledge base system
- Add migration mechanism for config path changes
- Global knowledge base registry
- Auto-evict stale entries from global registry
- Init defaults to repo-local hooks, --global for user-wide
- Add migrate path overrides, split skills, and remove state file

### Changed

- Normalize naming — marker, package, and docs
- Rename global registry index to core.md

### Documentation

- Audit and fix drift across all docs and skill
- Update install and contributor guides for uv sync
- Add CHANGELOG.md

### Fixed

- Resolve gap-analysis blockers and flatten kb_dir resolution

### Maintenance

- Add pre-commit hooks and align dependencies
- Add Makefile and fix README stale references
- Add GitHub workflows, local PyPI registry, and act support
- Update workflows to 2026 standards with SHA pinning
- Add mypy to dev dependencies for CI type-check gate

## Earlier Work

See git log for the full commit history prior to formal changelog adoption.
