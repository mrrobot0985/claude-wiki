# Implementation Plan — Road to v1.0

> **Status: active.** Tracks the push to the v1.0 stable release. The completed
> ADR-006 execution plan that previously lived here is preserved in
> [ADR-006](adr/006-vault-naming-and-obsidian-graph-hygiene.md) and in git
> history.

## Goal

Ship a **v1.0.0 stable** release: a frozen, documented surface (CLI, hooks,
lock-file schema, article frontmatter) backed by a reliable, signed release
pipeline, with cross-platform packaging and a stability/semver policy — and a
**ruthless hardening + simplification pass** that fixes the concrete failures
flagged in the v0.13.\* external review (compile write surface, compile cost,
config/migration surprises, concurrency races, dead abstraction) without adding
new scope.

## v1.0 hardening & simplification plan (ADRs 008–016)

Ratified 2026-06-22 by both external reviewers (Brutal: "Ship it"; Honest: "A-").
ADRs 008–015 are **Accepted**; ADR-016 is **Rejected** (kept on record). The full
ADR bodies live as individual files under `docs/adr/` (ADR-008 through ADR-016);
the summary table below tracks their status.

### Execution discipline

- Execute the 5 phases as written. **Add nothing else.** No new features, no
  new abstractions, no speculative seams.
- After Phase 1: **regression pass** on hooks + `compile --all` + Obsidian graph
  view before starting Phase 2+ (Honest).
- After v1.0.0: **architecture freeze.** No redesign churn for a while.

### Reconciliation notes (ground-truth verification against current code)

- `object.__setattr__` in `ProjectConfig.__post_init__` is NOT a smell —
  idiomatic + tested (`tests/test_models.py:180-197`).
- Path resolution is already centralized in `ConfigManager`
  (`config.py:230-300`); ADR-010 is scoped to deduping 2–3 helpers +
  lazy-migration removal, not a `PathResolver` rewrite.
- `.claude-wiki.lock` holds only config (runtime state is in the registry) —
  the "config/state mix" criticism is false.
- ADR-002 cross-filesystem rollback check is documented but UNIMPLEMENTED
  (`migration.py`) — concrete risk, addressed in ADR-010.
- Daily-log append race (`flush.py:214-238`) — unguarded RMW, in ADR-013.

### Already fixed — do NOT re-litigate

Hook input validation, timezone crash tests, wheel-install smoke test
(CI smoke job + `tests/test_packaging.py`), `.lock` config/state separation,
drift-guard tests (healthy insurance).

### Roadmap (5 phases, security-first)

#### Phase 1 — Security & compile safety

| #   | Item                                                                                                 | Failure solved                                                                   | Files                                  | Status    |
| --- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------- | --------- |
| 1.1 | Sandbox compile writes: drop `acceptEdits`, constrained response schema, Python-side path validation | LLM writes anywhere under `repo_root`; no traversal guard (`compile.py:261-269`) | `commands/compile.py`, new `writer.py` | clear-cut |
| 1.2 | Path-traversal + category guard on generated filenames                                               | `../`/absolute paths could escape `kb_root`                                      | `writer.py`, tests                     | clear-cut |
| 1.3 | Compile cost control: context cap, per-log USD cap (reuse `total_cost_usd`), opt-in `--model`        | $7.79/2 logs; no budget (`compile.py:186-279`)                                   | `commands/compile.py`, `models.py`     | clear-cut |
| 1.4 | Schema-validate LLM output (frozen dataclasses) before writing                                       | LLM-written files unchecked                                                      | `writer.py`, `catalog_utils.py`        | clear-cut |

**Phase 1 exit gate:** full regression pass on hooks + `compile --all` + Obsidian
graph view before starting Phase 2 (Honest).

#### Phase 2 — Concurrency hardening

| #   | Item                                                              | Failure solved                            | Files                 | Status    |
| --- | ----------------------------------------------------------------- | ----------------------------------------- | --------------------- | --------- |
| 2.1 | Lock daily-log append (`daily.log.lock`, per-repo)                | RMW race (`flush.py:214-238`)             | `flush.py`            | clear-cut |
| 2.2 | Lock `state.json` RMW (`state.json.lock`)                         | RMW race (`compile.py:373-438`)           | `commands/compile.py` | clear-cut |
| 2.3 | Per-repo compile serialization (covered by the `state.json` lock) | two concurrent compiles interleave        | `commands/compile.py` | clear-cut |
| 2.4 | Keep existing registry `fcntl` lock                               | already correct (`global_index.py:60-84`) | ---                   | clear-cut |

#### Phase 3 — Config/path consolidation

| #   | Item                                                                                                    | Failure solved                                                              | Files                                       | Status    |
| --- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------- | --------- |
| 3.1 | Dedupe path helpers into `ConfigManager`                                                                | `global_index._resolve_path`, `status._check_daily` duplicate logic         | `global_index.py`, `status.py`, `config.py` | clear-cut |
| 3.2 | Dedupe `ProjectConfig` validation (keep dataclasses)                                                    | validation duplicated in `__post_init__` + `from_dict` (`models.py:25-111`) | `models.py`, `config.py`                    | clear-cut |
| 3.3 | Remove lazy migration from `load()`; refuse-with-actionable-error on legacy; `migrate` is the only path | side-effecting config reads (`config.py:103-214`)                           | `config.py`, `cli.py`, `migration.py`       | clear-cut |
| 3.4 | Implement ADR-002 cross-filesystem pre-flight + warning inside `migrate`                                | documented but missing (`migration.py`)                                     | `migration.py`                              | clear-cut |

#### Phase 4 — Abstraction removal

| #   | Item                                                                             | Failure solved                                                                                       | Files                                   | Status    |
| --- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------- | --------- |
| 4.1 | Explicit command registry; kill `pkgutil` discovery                              | import errors silently swallowed (`cli.py:168-176`)                                                  | `cli.py`, `commands/__init__.py`        | clear-cut |
| 4.2 | Explicit hook registry                                                           | same pattern (`hooks.py:52-60`)                                                                      | `hooks.py`, `hook_handlers/__init__.py` | clear-cut |
| 4.3 | Drop unused Protocols/factories                                                  | single-implementation seams (`interfaces.py`, `factories.py`)                                        | `interfaces.py`, `factories.py`, tests  | clear-cut |
| 4.4 | Remove dead code                                                                 | `_format_link` (`global_index.py:270-276`), `resolve_catalog` None branch (`catalog_utils.py:91-97`) | `global_index.py`, `catalog_utils.py`   | clear-cut |
| 4.5 | Keep `argparse`; fix `_completions.py` private-API brittleness only if it recurs | private `argparse` internals (`_completions.py:35`)                                                  | `_completions.py`                       | clear-cut |

#### Phase 5 — Layout freeze & v1.0 release

| #   | Item                                                | Failure solved              | Files                            | Status                  |
| --- | --------------------------------------------------- | --------------------------- | -------------------------------- | ----------------------- |
| 5.1 | ADR-014: freeze layout v2                           | users fear another redesign | `docs/adr/014`                   | clear-cut               |
| 5.2 | Remove legacy v1 migration code (post grace period) | dead weight after freeze    | `config.py`, `migration.py`      | in progress             |
| 5.3 | v1.0.0 tag + CHANGELOG                              | no stable baseline          | `pyproject.toml`, `CHANGELOG.md` | **needs user sign-off** |

### Testing & verification requirements (Honest)

Folded into the relevant phases — not a separate phase, no new scope:

- **`writer.py` (ADR-012):** aggressive negative tests — path-traversal attempts
  (`../`, absolute paths, symlinks), bad slugs, out-of-set categories, oversized
  output, malformed/missing JSON fields. The failure path is the security
  guarantee; test it hard.
- **Migration (ADR-010):** tests must now explicitly invoke `migrate` (no implicit
  side-effect path). Cover the legacy-detect → refuse-with-actionable-error path
  and the cross-FS warning path.
- **Concurrency (ADR-013):** simulate concurrent flushes/compiles (threads +
  mocked FS, or `pytest` `tmp_path` with two threads) — assert no dropped
  daily-log entries and no clobbered `state.json`.
- **Validation factory (ADR-008):** tests assert the single factory exercises
  every check `__post_init__` used to (timezone, path expansion, hour range) — no
  divergence.
- **Phase 1 exit gate:** full regression pass on hooks + `compile --all` +
  Obsidian graph view before starting Phase 2.

### ADR status summary

| ADR | Title                                    | Status   |
| --- | ---------------------------------------- | -------- |
| 008 | Keep dataclasses; dedupe validation      | Accepted |
| 009 | Explicit command/hook registries         | Accepted |
| 010 | Consolidate paths; remove lazy migration | Accepted |
| 011 | Compile cost control                     | Accepted |
| 012 | Constrained write schema                 | Accepted |
| 013 | Advisory `fcntl` locks                   | Accepted |
| 014 | Freeze layout v2                         | Accepted |
| 015 | Keep argparse                            | Accepted |
| 016 | MCP server                               | Rejected |

Every roadmap item is **clear-cut** except **5.3 (v1.0.0 tag)** which needs user
sign-off.

## Done

### Features (shipped through v0.13.0)

- `compile --max-logs` cost guard (alias `--limit`, oldest-first, default
  unlimited) — v0.12.0
- `lint` catalog↔article completeness check (`uncatalogued_article`,
  `stale_catalog_entry`) + `lint --fix`/`--dry-run` safe auto-repairs — v0.11.0,
  v0.12.0
- `status --json` machine-readable health output — v0.13.0
- `claude-wiki graph` topology report (orphans, hubs, connected components) with
  a shared `graph_utils` module — v0.13.0
- `query` scope filters (`--category`, `--tag`, `--since`, `--max-chars`),
  `query --json`, `lint --json`, `tags` command + `--tag` filter — v0.9.0–v0.10.0
- Atomic `flush` writes (daily log + dedup state) — v0.12.0
- Shell completions (bash/zsh/fish, drift-guarded) + man page — v0.10.0

### Release pipeline (hardened)

- Tag-driven: signed tags (`git tag -s`, non-prefixed identity → GitHub-verified)
  trigger `release.yml`.
- `release.yml` `verify-main` rejects unverified tags before build/publish
  (signed-tag gate).
- `publish` to PyPI via trusted publishing (OIDC, checkout-free).
- `github_release` job creates a GitHub Release (wheel + sdist + CHANGELOG notes),
  checkout-free (notes extracted from the sdist) and idempotent (create-or-upload).
- Only `verify-main` and `build` check out the source (where actually needed).

### Docs & policy

- Stability & SemVer policy (`docs/reference/stability.md`) + 0.x→1.0 upgrade
  guide (`docs/how-to/upgrade-to-v1.md`).
- How-tos for JSON output, `graph`, tags, completions, lint-ignore, query scope,
  migration, hooks.
- README refreshed for the v0.12/v0.13 feature set.
- ADRs 005–007 (directory redesign, vault naming/graph hygiene, no wikilinks to
  daily logs).

### Merge/signing discipline

- All merges are `--squash` (the repo enforces `required_linear_history` +
  `required_signatures`, so `--merge`/`--rebase` are blocked). PR commits use the
  ID-prefixed author email (no co-author trailer); tags use the non-prefixed
  signed identity (verified). See `CLAUDE.md` → "Commit signing & PR merges".

## Remaining (gated on environment / user decision)

- **Cross-platform packaging** — open issues:

  - [#149](https://github.com/mrrobot0985/claude-wiki/issues/149) Homebrew
    formula (macOS)
  - [#150](https://github.com/mrrobot0985/claude-wiki/issues/150) AUR package
    (Arch Linux)
  - [#151](https://github.com/mrrobot0985/claude-wiki/issues/151) Scoop manifest
    (Windows)

  Each needs its target OS to verify the install end-to-end
  (`brew install` / `makepkg -si` / `scoop install`); not verifiable from a Linux
  sandbox.

- **v1.0.0 declaration** — the user decides when to jump from 0.13.x to 1.0.0
  once the packaging reach and the v1.0 hardening plan (above) are in place.

## Released versions

0.6.0 → 0.7.0 → 0.8.0 → 0.9.0 → 0.10.0 → 0.11.0 → 0.12.0 → 0.13.0 (all on PyPI;
v0.12.0 and v0.13.0 also have GitHub Releases with wheel + sdist).
