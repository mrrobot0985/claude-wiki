# Changelog

All notable changes to this project are documented in this file.

## [unreleased]

### Added

- Core knowledge base system: compile, query, lint, migrate CLI commands and Claude Code hooks.
- Migration mechanism for config path changes with --dry-run and overlap prevention.
- Global knowledge base registry at `~/.local/share/claude-wiki/core.md`.
- Auto-eviction of stale entries from global registry.
- Repo-local hooks by default; `--global` flag for user-wide installation.
- Pre-commit hooks (gitleaks, ruff, mdformat, mypy, pytest, conventional-pre-commit).
- GitHub Actions CI workflow with Python 3.12-3.14 matrix.
- GitHub Actions release workflow for PyPI trusted publishing.
- Makefile with dev, test, lint, format, typecheck, precommit, build, and clean targets.
- Local PyPI registry Makefile targets for testing package publishing.

### Changed

- **Breaking**: Default `kb_dir` changed from relative `"knowledge"` to sentinel `"project"`, resolving to `repo/.claude/knowledge/`.
- Updated CI workflow triggers to run on all branches.
- Bumped pre-commit hook versions: ruff 0.5.0 to 0.15.18, mypy 1.10.1 to 2.1.0, gitleaks 8.18.2 to 8.30.1, conventional-pre-commit 3.2.0 to 4.4.0.
- Aligned README and install docs with uv-first workflow.

### Fixed

- Corrected `uvx --from` syntax in generated hook commands.
- Fixed mypy strict failure in query command options annotation.
- Fixed empty-destination bug in migration `shutil.move` behavior.
- Removed documentation references to non-existent `.claude-wiki.state.json`.

### Documentation

- Audited and fixed drift across all docs and skills.
- Added `reports_dir` to schema examples and data models.
- Documented `kb_dir` project/user/custom modes in configuration reference.
- Updated architecture resolution priority chain.

## Earlier Work

See git log for the full commit history prior to formal changelog adoption.
