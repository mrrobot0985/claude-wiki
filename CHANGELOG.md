# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

### Added

- `.gitignore` entries for `.claude-wiki.lock` and `coverage.json`
- `CONTRIBUTING.md` at repo root with branch naming and PR checklist
  ([#78](https://github.com/mrrobot0985/claude-wiki/issues/78))
- GitHub issue templates for bug reports and feature requests
  ([#78](https://github.com/mrrobot0985/claude-wiki/issues/78))
- Expanded quickstart tutorial with project-vs-user mode, sample output, and
  Obsidian integration ([#77](https://github.com/mrrobot0985/claude-wiki/issues/77))

## [0.5.0] - 2026-06-20

### Added

- *(cli)* Add --version flag, __version__, and --path for query/lint ([#57](https://github.com/mrrobot0985/claude-wiki/issues/57))

### Documentation

- Align all documentation with v0.4.0 implementation ([#41](https://github.com/mrrobot0985/claude-wiki/issues/41))
- Align CLI and config reference with shipped behavior ([#61](https://github.com/mrrobot0985/claude-wiki/issues/61))

### Fixed

- *(registry)* Bound lock wait, handle unreadable files, atomic core.md ([#60](https://github.com/mrrobot0985/claude-wiki/issues/60))
- Validate timezone, expand ~ in paths, guard empty slug and max_turns=0 ([#58](https://github.com/mrrobot0985/claude-wiki/issues/58))
- *(lint)* Normalize wikilink targets before resolving and counting ([#59](https://github.com/mrrobot0985/claude-wiki/issues/59))

### Maintenance

- *(deps)* Bump pydantic-settings from 2.14.1 to 2.14.2 ([#40](https://github.com/mrrobot0985/claude-wiki/issues/40))
- Validate release tag version and add installed-wheel smoke test ([#62](https://github.com/mrrobot0985/claude-wiki/issues/62))

### Testing

- Isolate suite from live user state ([#56](https://github.com/mrrobot0985/claude-wiki/issues/56))

## [0.4.0] - 2026-06-20

### Added

- ADR-006: Vault naming and Obsidian graph hygiene (#38)
- Per-repo catalog renamed from `index.md` to `{repo_name}.md`
- `core.md` uses Obsidian wikilinks for cross-repo navigation
- Plain-text directory references (no phantom markdown links)
- `claude-wiki rename-catalog` command with `--dry-run`
- SessionStart hook injects `{repo_name}.md` with legacy `index.md` fallback

### Changed

- Version bump to 0.4.0 (#39)

## [0.3.0] - 2026-06-20

### Added

- ADR-005: KB directory redesign with XDG-compliant paths
- `layout_version` field to `.claude-wiki.lock` for migration tracking
- Lazy migration from layout v1 to v2 with automatic data relocation
- `make install-precommit` target for git hook setup
- Documentation for pre-commit hook installation in README and install guide

### Changed

- User-wide vault namespace renamed to `claude-wiki-vault`
- Machine state files moved to XDG state/cache directories
- Daily logs relocated to XDG data directory in user mode
- `repo_owner` inference now always re-infers from git remotes during init

### Removed

- Daily backlink mutation and symlink creation (daily logs are immutable)
- `reports_dir` deprecation warning in CLI

### Fixed

- ruff formatting consistency across source and test files

## [0.2.0] - 2026-06-19

### Added

- Interactive initialization mode (`claude-wiki init` prompts when stdin is a TTY)
- Git remote owner inference for `repo_owner` (supports HTTPS and SSH remotes)
- Bidirectional provenance: compiled articles backlink to source daily logs
- Daily log symlink in KB root for cross-mode navigation (`kb_root/daily`)
- Migration rollback on partial failure (LIFO reversal of completed moves)
- Registry advisory file lock for concurrent read-modify-write safety
- Registry backup on corruption (`.registry.json.<timestamp>.broken`)

### Fixed

- Config path normalization: `get_kb_root()` always returns resolved absolute paths
- Atomic lock-file I/O: crash-safe writes via temp file + `os.replace()`
- Corrupt `.claude-wiki.lock` now raises `ConfigError` with file path context
- Migration false success when move is skipped (`migrated=False` when dest non-empty)
- Migration path comparison: resolves symlinks and `..` before comparing
- Migration overlap guard: rejects containment, not just equality
- Migration crash on file destinations: `dst.is_dir()` guard before `iterdir()`
- `ProjectConfig` mutable defaults: uses `default_factory` for `Path` fields
- `ProjectConfig` validation: non-empty strings, `compile_after_hour` in 0–23
- Registry corruption: validates entries individually, skips malformed with warning
- Registry relative `repo_root`: normalizes to absolute on register, preserves legacy
- `core.md` cross-repo navigation: per-repo sections with repo root and daily links

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
