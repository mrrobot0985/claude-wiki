# Changelog

All notable changes to this project are documented in this file.

## [0.1.1] - 2026-06-19

### Documentation

- Update dev skill with branching, CI, and release procedures

### Fixed

- Migration respects kb_dir mode resolution (user/project)

### Maintenance

- Automate PyPI publish on tag push
- Add release safeguard, optimize CI path filtering, and fix mdformat coverage

## [0.1.0] - 2026-06-19

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
- Release v0.1.0
- Release v0.1.0

### Fixed

- Resolve gap-analysis blockers and flatten kb_dir resolution

### Maintenance

- Add pre-commit hooks and align dependencies
- Add Makefile and fix README stale references
- Add GitHub workflows, local PyPI registry, and act support
- Update workflows to 2026 standards with SHA pinning
- Add mypy to dev dependencies for CI type-check gate
- Add cliff.toml for automated CHANGELOG generation
- Make PyPI publish conditional on workflow_dispatch input
- Fix actions/upload-artifact and download-artifact SHA pins
- Fix uv publish command — remove invalid --from-dist flag

### Reverted

- Undo v0.1.0 release

## Earlier Work

See git log for the full commit history prior to formal changelog adoption.
