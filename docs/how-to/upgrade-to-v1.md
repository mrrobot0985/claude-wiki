# Upgrade to v1.0

This guide walks you through upgrading an existing claude-wiki install from a 0.x release to the v1.0 stable release. It uses only commands that already exist today.

If you are on v0.8 or newer, you typically need no data migration — the steps below are mostly a verification checklist.

## Pre-flight: diagnose repository health

Run `status` in each repository that uses claude-wiki:

```bash
claude-wiki status
```

Fix every error before continuing. Warnings (for example, an empty daily directory or no compiled articles yet) are acceptable, but errors such as a missing `.claude-wiki.lock`, corrupt config, or broken hooks must be resolved first.

## What v1.0 changes for existing installs

### Catalog rename already happened in v0.4.0

Per [ADR-006](../adr/006-vault-naming-and-obsidian-graph-hygiene.md), the per-repo catalog was renamed from `index.md` to `{repo_name}.md` (for example, `claude-wiki.md`). This change shipped in v0.4.0.

- If you initialized your knowledge base on v0.4.0 or later, your catalog is already named correctly.

- If you are on a release older than v0.4.0, preview the rename and then apply it:

  ```bash
  claude-wiki rename-catalog --dry-run
  claude-wiki rename-catalog
  ```

### Directory-layout migration is explicit

[ADR-005](../adr/005-kb-directory-redesign.md) introduced `layout_version: "2"` and separated vault, machine-state, and cache directories. Lazy auto-migration was removed in v0.13.x; the only migration path is explicit `claude-wiki migrate`. If you are on v0.8 or newer with `layout_version: "2"`, no action is needed.

Layout version 1 is no longer supported as of v1.0.0. If you are still on a 0.x release with an older `layout_version`, run `claude-wiki migrate` before upgrading to v1.0.0.

If `claude-wiki status` passes, your repository is already on layout version 2.

### No flags removed or renamed

Between the latest 0.x release and v1.0, no CLI flags were removed or renamed. Existing scripts and aliases continue to work unchanged.

## Migrate data if paths changed

If you want to switch the knowledge base from project mode to user mode, move daily logs to a different directory, or change any other path setting, preview and then apply the move:

```bash
claude-wiki migrate --dry-run
claude-wiki migrate
```

`migrate` compares the previously saved `.claude-wiki.lock` against the current configuration (including any CLI overrides) and moves `kb_dir`, `daily_dir`, and state directories as needed. `--dry-run` shows exactly what would move without touching disk.

## Post-flight: verify structure and health

Run a structural lint to catch any catalog or wikilink drift after the upgrade:

```bash
claude-wiki lint --structural-only
```

Then re-run `status` to confirm everything is green:

```bash
claude-wiki status
```

If both commands pass, the repository is ready for the v1.0 release line.

## When you need no action

Users on v0.8 or newer generally need only the pre-flight `status` check. The catalog rename and directory-layout migration were both completed before v0.8, so the upgrade is a matter of confirming health rather than moving data.
