# Implementation Plan — Road to v1.0

> **Status: active.** Tracks the push to the v1.0 stable release. The completed
> ADR-006 execution plan that previously lived here is preserved in
> [ADR-006](adr/006-vault-naming-and-obsidian-graph-hygiene.md) and in git
> history.

## Goal

Ship a **v1.0.0 stable** release: a frozen, documented surface (CLI, hooks,
lock-file schema, article frontmatter) backed by a reliable, signed release
pipeline, with cross-platform packaging and a stability/semver policy.

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
  once the packaging reach is in place.

## Released versions

0.6.0 → 0.7.0 → 0.8.0 → 0.9.0 → 0.10.0 → 0.11.0 → 0.12.0 → 0.13.0 (all on PyPI;
v0.12.0 and v0.13.0 also have GitHub Releases with wheel + sdist).
