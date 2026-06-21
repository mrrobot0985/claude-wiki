# Changelog

All notable changes to this project are documented in this file.

## [Unreleased]

Nothing yet.

## [0.12.0] - 2026-06-21

### Added

- `compile --max-logs N` (alias `--limit`) cost guard: caps the number of daily
  logs compiled in one run, oldest pending first, with an explicit truncation
  summary. Applies to both the default changed-only selection and `--all`;
  `--file` is exempt; default is unlimited (no behavior change when absent)
  ([#139](https://github.com/mrrobot0985/claude-wiki/pull/139))
- `lint` catalog↔article completeness check, wired into the structural checks
  (runs in `--structural-only` and full modes, no LLM call): emits
  `uncatalogued_article` (warning) for an article missing from the catalog and
  `stale_catalog_entry` (error) for a catalog reference that resolves to no
  file. The catalog is the primary retrieval surface, so drift is now caught
  ([#138](https://github.com/mrrobot0985/claude-wiki/pull/138))
- v1.0 stability & SemVer policy (`docs/reference/stability.md`) and a 0.x → 1.0
  upgrade guide (`docs/how-to/upgrade-to-v1.md`), linked from `docs/index.md`
  ([#140](https://github.com/mrrobot0985/claude-wiki/pull/140))

### Fixed

- `flush` now writes the daily log and the `last-flush.json` dedup state
  atomically (same-directory tempfile + `os.replace`), so a backgrounded flush
  interrupted mid-write can no longer corrupt the immutable daily log (the
  compilation source of truth) or the dedup state
  ([#137](https://github.com/mrrobot0985/claude-wiki/pull/137))

### Changed

- CLI reference and man page resynced for `--max-logs`; stability policy lists
  the current per-command flag set including `--max-logs`

## [0.11.0] - 2026-06-21

### Added

- `lint --fix` and `--dry-run` for safe structural auto-fixes (missing trailing
  newline, `[[daily/...]]` wikilink → plain text per ADR-007), wiring up the
  previously dead `auto_fixable` field
  ([#126](https://github.com/mrrobot0985/claude-wiki/issues/126))
- `compile --continue-on-error` and a fail-fast default: `compile` now exits
  non-zero when a daily log fails to compile (silent partial compilation no
  longer masks failures in CI) ([#127](https://github.com/mrrobot0985/claude-wiki/issues/127))
- How-to guides for tags, shell completions, lint ignore files, `--json` CI
  usage, and query scope filters
  ([#129](https://github.com/mrrobot0985/claude-wiki/issues/129))
- Pre-publish smoke gate in `release.yml` (installs wheel + sdist, exercises
  entry points, bootstraps `init`), plus sdist-completeness and man-page
  coverage tests ([#130](https://github.com/mrrobot0985/claude-wiki/issues/130))

### Fixed

- PreCompact hook now shares `flush.extract_conversation_context` instead of a
  drifting duplicate parser ([#128](https://github.com/mrrobot0985/claude-wiki/issues/128))

### Changed

- CLI reference and man page resynced for `--fix`/`--dry-run`/`--continue-on-error`
  and the current subcommands

## [0.10.0] - 2026-06-20

### Added

- `query` scope filters: `--category` (repeatable), `--since YYYY-MM-DD`, and
  `--max-chars N` cap, so queries no longer read the entire KB into one prompt
  ([#117](https://github.com/mrrobot0985/claude-wiki/issues/117))
- `lint` frontmatter-schema enforcement (required `title`/`sources` are errors;
  `aliases`/`tags`/`created`/`updated` are warnings), a `.claude-wiki-lint-ignore`
  file (`path::check::reason`, fnmatch globs), and a `--threshold N` override
  ([#118](https://github.com/mrrobot0985/claude-wiki/issues/118))
- YAML tag indexing: a `claude-wiki tags` command, a repeatable `query --tag`
  filter (union, composes by AND with the other scope filters), and a
  `tag_single_use` lint suggestion ([#119](https://github.com/mrrobot0985/claude-wiki/issues/119))
- Bash/zsh/fish shell completions (generated from the live parser with a
  drift-guard test), a `claude-wiki.1` man page shipped in the wheel, and richer
  PyPI classifiers/URLs ([#120](https://github.com/mrrobot0985/claude-wiki/issues/120))

### Changed

- CLI reference (`docs/reference/cli.md`) resynced against the actual
  `claude-wiki --help` output to cover all new query/lint flags and the `tags`
  subcommand

## [0.9.0] - 2026-06-20

### Added

- `query --json` and `lint --json` emit machine-readable output, plus a
  `--fail-on-warning` flag and a documented stable exit-code contract for both
  commands (query `0`/`1`/`2`, lint `0`/`1`/`2`)
  ([#108](https://github.com/mrrobot0985/claude-wiki/issues/108))
- `SECURITY.md`, `CODE_OF_CONDUCT.md`, and a `Funding` project URL
  ([#109](https://github.com/mrrobot0985/claude-wiki/issues/109))

### Changed

- CLI reference (`docs/reference/cli.md`) resynced against the actual
  `claude-wiki --help` output — every subcommand and shipped flag documented,
  `--version` corrected to a global option
  ([#109](https://github.com/mrrobot0985/claude-wiki/issues/109))

### Fixed

- `ConfigManager` lazy v1→v2 layout migration is now atomic with LIFO rollback on
  partial failure, so a half-finished migration no longer leaves the knowledge base
  in a partially-moved state ([#106](https://github.com/mrrobot0985/claude-wiki/issues/106))
- Hook handler and CLI/hook auto-discovery failures are now logged instead of
  silently swallowed, giving users a debug trail while keeping hook return codes
  non-fatal ([#107](https://github.com/mrrobot0985/claude-wiki/issues/107))

## [0.8.0] - 2026-06-20

### Added

- `init` aborts with exit 1 when global claude-wiki hooks are already
  installed, pointing to `--no-hooks` or `--global` to prevent double-firing
  ([#69](https://github.com/mrrobot0985/claude-wiki/issues/69))
- `migrate --kb-dir` accepts the literal `user`/`project` modes and moves
  `daily_dir` and the machine-state directory on a mode switch, with rollback
  on partial failure ([#70](https://github.com/mrrobot0985/claude-wiki/issues/70))

## [0.7.0] - 2026-06-20

### Added

- `--kb-dir {project|user|PATH}` and `--daily-dir PATH` flags on `init` for
  non-interactive onboarding into project or user mode
  ([#65](https://github.com/mrrobot0985/claude-wiki/issues/65))

### Documentation

- Document `--version`, `--path`, timezone validation, and `~` expansion in the
  CLI and config reference docs
  ([#99](https://github.com/mrrobot0985/claude-wiki/issues/99))

## [0.6.0] - 2026-06-20

### Added

- `claude-wiki status` diagnostic command — checks lock file, daily logs, KB catalog, hooks, registry ([#88](https://github.com/mrrobot0985/claude-wiki/issues/88))
- Integration test exercising full `init -> compile -> query -> lint` lifecycle with mocked LLM calls ([#84](https://github.com/mrrobot0985/claude-wiki/issues/84))
- How-to guide for migrating from project mode to user mode ([#85](https://github.com/mrrobot0985/claude-wiki/issues/85))
- CI job to validate example lock JSON, markdown formatting, and daily log filenames ([#86](https://github.com/mrrobot0985/claude-wiki/issues/86))
- Architecture deep-dive for Obsidian graph hygiene — naming, wikilinks, directory references, troubleshooting table ([#87](https://github.com/mrrobot0985/claude-wiki/issues/87))
- *(cli)* Add --no-hooks to init to skip hook install
  ([#66](https://github.com/mrrobot0985/claude-wiki/issues/66))
- `.gitignore` entries for `.claude-wiki.lock` and `coverage.json`
- *(cli)* Add `registry` list/show/remove/clean subcommand ([#67](https://github.com/mrrobot0985/claude-wiki/issues/67))
- PyPI and CI badges to README ([#75](https://github.com/mrrobot0985/claude-wiki/issues/75))
- `CONTRIBUTING.md` at repo root with branch naming and PR checklist
  ([#78](https://github.com/mrrobot0985/claude-wiki/issues/78))
- GitHub issue templates for bug reports and feature requests
  ([#78](https://github.com/mrrobot0985/claude-wiki/issues/78))
- Expanded quickstart tutorial with project-vs-user mode, sample output, and
  Obsidian integration ([#77](https://github.com/mrrobot0985/claude-wiki/issues/77))
- `examples/minimal-walkthrough` with synthetic daily log and compiled KB ([#76](https://github.com/mrrobot0985/claude-wiki/issues/76))
- `claude-wiki register [--path]` command to register an existing `.claude-wiki.lock`
  without re-running `init` ([#68](https://github.com/mrrobot0985/claude-wiki/issues/68))

### Changed

- PyPI classifier upgraded from Development Status :: 3 - Alpha to 4 - Beta ([#75](https://github.com/mrrobot0985/claude-wiki/issues/75))

### Removed

- Temporary `index.md` fallback from SessionStart hook and catalog resolution ([#74](https://github.com/mrrobot0985/claude-wiki/issues/74))

### Performance

- Build lint link graph once and read KB index and articles once per compile run to avoid O(n²) file reads ([#53](https://github.com/mrrobot0985/claude-wiki/issues/53))

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
