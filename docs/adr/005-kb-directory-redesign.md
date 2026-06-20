# ADR-005: Knowledge Base Directory Redesign

## Status

Accepted

> Implemented in commit `09baaec` and released in v0.3.0. Lazy migration, XDG state/cache dirs, and daily log relocation are all active.

## Context

The claude-wiki project stores four artifact families in overlapping trees, producing daily friction:

1. **Daily conversation logs** live under `daily/` inside the source repo. Every session appends a markdown file, so the working tree carries an uncommitted change that risks accidental commits of personal or proprietary context.
1. **Machine-generated operational files** (`state.json`, `logs/flush.log`, `logs/last-flush.json`, `reports/lint-*.md`) are stored inside the same `kb_root/` that is meant to be an Obsidian vault of human-readable articles. Markdown reports and stray temp `.md` files appear in Graph view.
1. **The compiler mutates source logs**. `_update_daily_backlinks` in `compile.py` appends a `## Compiled Knowledge` section to files in `daily/`, breaking the stated immutability of the daily log and creating circular coupling between source and output.
1. **Absolute paths in the global registry** become invalid when a repo is cloned to a different path on another machine. The registry mixes machine JSON (`.registry.json`) with regenerated human markdown (`core.md`) in the same directory.
1. **Config has no machine-state abstraction**. `ProjectConfig` exposes `kb_dir`, `daily_dir`, and `reports_dir`, but `flush.py`, `compile.py`, and `lint.py` hardcode subdirectories under `kb_root`, making it impossible to keep the vault clean.

External constraints also apply:

- XDG Base Directory conventions separate **config** (`~/.config`), **user data** (`~/.local/share`), **machine state** (`~/.local/state`), and **ephemeral cache** (`~/.cache`). Operational logs and hashes belong in state or cache, not in share.
- Obsidian's Graph view indexes every markdown file under the vault root recursively. Visible subdirectories like `logs/` and `reports/` pollute the graph; raw daily logs would create hundreds of disconnected nodes.
- PKB best practices keep the immutable capture layer (daily notes) distinct from the compiled evergreen layer (wiki articles), with raw notes treated as the source of truth.
- Repo root cleanliness matters: a `daily/` folder at the top level makes the repository look like a journal rather than a code project.

## Goals

1. Machine-generated files never appear in the Obsidian graph.
1. Human-readable KB articles remain in a single clean vault.
1. Daily logs have a clear ownership model and stay out of `git add .`.
1. Cross-device syncing works for the parts humans care about.
1. Running `ls` at the repo root shows only code, not data.
1. The global vault can aggregate multiple repos for cross-project graph viewing.

## Decision

Adopt a **mode-aware directory layout** with two structural invariants:

- **The vault contains only human-readable knowledge articles and navigation.** No machine files, no daily logs, no reports.
- **Daily logs and machine files live outside the vault in every mode.**

### User-wide mode — global vault at `~/.local/share/claude-wiki-vault/`

The user opens `~/.local/share/claude-wiki-vault/` as an Obsidian vault. `core.md` sits at the vault root and links to per-repo KBs nested underneath, enabling a single graph view across all repos.

Because Obsidian recursively indexes everything under the vault root, **daily logs cannot live inside this tree.** They go to a sibling XDG data directory.

```text
# Obsidian vault root (human-readable only)
~/.local/share/claude-wiki-vault/
├── .obsidian/                         # Obsidian config, ignored by graph
├── .registry.json                      # JSON, ignored by graph
├── core.md                             # Global navigation hub
└── <owner>/                            # Per-repo KBs
    └── <repo>/
        ├── {repo_name}.md
        ├── log.md
        ├── concepts/*.md
        ├── connections/*.md
        └── qa/*.md

# Daily logs — outside vault, still XDG data
~/.local/share/claude-wiki-daily/
└── <owner>/
    └── <repo>/
        └── 2026-06-19.md

# Machine state
~/.local/state/claude-wiki/repos/<owner>/<repo>/
├── state.json
└── logs/
    ├── flush.log
    └── last-flush.json

# Ephemeral reports and temp files
~/.cache/claude-wiki/repos/<owner>/<repo>/
├── reports/
│   └── lint-2026-06-19.md
└── session-flush-*.md
```

### Project mode — vault is a repo subdirectory

Everything stays in the repo but is nested under `.claude/` to keep the repo root clean. The vault root is `.claude/knowledge/`; siblings live outside the vault but inside the `.claude/` subtree.

```text
# Project repo
/home/mrrobot0985/workspaces/personal/repos/mrrobot0985/claude-wiki/
├── src/
├── tests/
├── docs/
├── .claude/
│   ├── knowledge/           # ← vault root (Obsidian opens this)
│   │   ├── {repo_name}.md
│   │   ├── log.md
│   │   ├── concepts/*.md
│   │   ├── connections/*.md
│   │   └── qa/*.md
│   ├── daily/               # immutable source of truth
│   │   └── 2026-06-19.md
│   ├── state/               # machine state (sibling to vault)
│   │   ├── state.json
│   │   └── logs/
│   │       ├── flush.log
│   │       └── last-flush.json
│   └── reports/             # ephemeral (sibling to vault)
│       └── lint-2026-06-19.md
└── ...
```

### Unified layout summary

| Artifact        | User-wide path                               | Project path               | Bucket           | Rationale                                |
| --------------- | -------------------------------------------- | -------------------------- | ---------------- | ---------------------------------------- |
| Daily logs      | `~/.local/share/claude-wiki-daily/`          | `repo/.claude/daily/`      | **Data** (share) | Immutable source of truth; outside vault |
| KB vault        | `~/.local/share/claude-wiki-vault/<o>/<r>/`  | `repo/.claude/knowledge/`  | **Data** (share) | Human-readable articles                  |
| Global registry | `~/.local/share/claude-wiki-vault/`          | (same)                     | **Data** (share) | Human-readable `core.md` + JSON index    |
| `state.json`    | `~/.local/state/claude-wiki/repos/o/r/`      | `repo/.claude/state/`      | **State**        | Compilation hashes, costs                |
| Flush logs      | `~/.local/state/claude-wiki/repos/o/r/logs/` | `repo/.claude/state/logs/` | **State**        | Operational traces                       |
| Lint reports    | `~/.cache/claude-wiki/repos/o/r/reports/`    | `repo/.claude/reports/`    | **Cache**        | Ephemeral; safe to delete/regenerate     |
| Session temps   | `~/.cache/claude-wiki/repos/o/r/`            | `repo/.claude/reports/`    | **Cache**        | Temp context files for LLM calls         |

### Why the vault-at-root pattern works

Opening `~/.local/share/claude-wiki-vault/` as the vault enables a **unified knowledge graph**: `core.md` links to per-repo catalogs with wikilinks such as `[[local/claude-wiki/claude-wiki|claude-wiki]]`. Obsidian renders the entire multi-repo knowledge base as one interconnected graph.

This is only viable because the vault root is kept clean: `.registry.json` is JSON, `.obsidian/` is ignored, and per-repo KBs contain only evergreen articles. Daily logs live outside at `~/.local/share/claude-wiki-daily/` so they never appear as disconnected nodes.

## Consequences

- **Vault purity**: No machine file or daily log ever lives inside a vault root. Obsidian graph contains only human articles and `core.md`.
- **Root cleanliness**: In project mode, `ls` at the repo root never shows `daily/`, `knowledge/`, or `logs/`.
- **Immutability restored**: Daily logs are never mutated by `compile.py`. Provenance is tracked solely in article frontmatter (`sources:`) and `knowledge/log.md`.
- **XDG compliance**: Data, state, and cache each go to their canonical XDG bucket.
- **Cross-device safety**: All paths in `.claude-wiki.lock` and the registry should be stored as relative to `$HOME` (e.g. `~/.local/share/...` strings), so they resolve correctly on any machine.
- **Dot-directory preference**: In project mode, everything is under `.claude/`. Git users already ignore `.claude/` or at least expect non-source data there.
- **Backlink discipline**: Daily logs are raw source material, not part of the knowledge graph. Articles cite them in YAML frontmatter (`sources: [daily/2026-06-19.md]`) and plain text, never as wikilinks `[[daily/...]]`. This avoids broken links when daily lives outside the vault.

## Specific code changes

### 1. Add machine-state and cache helpers

Extend `ConfigManager` with:

- `get_machine_state_dir(repo_root, config) -> Path`
- `get_cache_dir(repo_root, config) -> Path`

Respect `XDG_STATE_HOME` and `XDG_CACHE_HOME` with fallbacks to `~/.local/state` and `~/.cache`.

### 2. Move operational file writes

- `flush.py`: replace `kb_root / "logs"` with `get_machine_state_dir(...) / "logs"`.
- `compile.py`: replace `kb_root / "state.json"` with `get_machine_state_dir(...) / "state.json"`.
- `lint.py`: replace `kb_root / "reports"` with `get_cache_dir(...) / "reports"`.
- `compile.py`: remove `_update_daily_backlinks`; stop mutating daily logs.

### 3. Move daily log default

For user-wide mode, change default `daily_dir` from `repo_root / "daily"` to `~/.local/share/claude-wiki-daily/<owner>/<repo>/`.
For project mode, change default from `repo_root / "daily"` to `repo_root / ".claude/daily"`.
Support `CLAUDE_WIKI_DAILY_DIR` and `.claude-wiki.lock` overrides.

### 4. Ensure session temps are cache

`write_context_file` in `flush.py` should write to `get_cache_dir(...)`, not `get_logs_dir(...)`.

### 5. Drop wikilink syntax for daily citations

Article templates and the compiler should use plain-text daily citations in the body and YAML frontmatter (`` `daily/YYYY-MM-DD.md` `` or `sources: [daily/YYYY-MM-DD.md]`), avoiding `[[daily/YYYY-MM-DD.md]]` wikilinks that would break when daily lives outside the vault.

### 6. Registry path normalization

Store `daily_dir` and `kb_root` as paths relative to `$HOME` in the lock file and registry, resolving with `Path.home()` at runtime.

## Migration path

1. Detect legacy layout: if `kb_root / "logs"` or `kb_root / "state.json"` exists, move to new directories and delete old paths.
1. Detect legacy daily dir: if `repo_root / "daily"` exists, offer to migrate to `.claude/daily/` (project mode) or `~/.local/share/claude-wiki-daily/` (user mode).
1. Update article templates to remove `[[daily/...]]` wikilinks; replace with plain-text citations.
1. Update `.claude-wiki.lock` with new `daily_dir` and `kb_dir` values.
1. Re-register with `GlobalIndexManager` using normalized relative paths.

## Bug fix: `repo_owner` inference in `init`

### Problem

`claude-wiki init` sets `repo_owner` to `"local"` even when the repository has a git remote that clearly identifies an owner (e.g., `mrrobot0985` from `https://github.com/mrrobot0985/claude-wiki.git`).

### Root cause

`_init` in `cli.py` loads the existing `.claude-wiki.lock` file first, then only re-infers `repo_owner` from git remotes when `--force` is passed or the lock file does not exist:

```python
defaults = loader.load(repo_root)
if args.force or not marker.exists():
    defaults = dataclasses.replace(
        defaults,
        repo_name=repo_root.name,
        repo_owner=owner_resolver.infer_repo_owner(repo_root),
    )
```

When the lock file was created before a git remote existed, or before `GitRemoteOwnerResolver` was implemented, it stores `"local"`. Subsequent `init` invocations without `--force` skip re-inference and perpetuate the stale value.

### Impact

With the vault-at-root layout, `repo_owner` drives the directory namespace. Stale `"local"` values mean:

- Every repo goes under `~/.local/share/claude-wiki-vault/local/<repo>/`
- Different users' forks of the same repo collide in the same directory
- Cross-repo graph navigation in `core.md` shows `local/<repo>` instead of meaningful ownership

### Fix

Change `init` to **always re-infer `repo_name` and `repo_owner`** when a git remote is present, regardless of `--force`:

```python
inferred_owner = owner_resolver.infer_repo_owner(repo_root)
if inferred_owner != "local" or args.force or not marker.exists():
    defaults = dataclasses.replace(
        defaults,
        repo_name=repo_root.name,
        repo_owner=inferred_owner,
    )
```

This is a **safe, idempotent** update: if the remote is parseable, use it; if not, preserve the existing value. Only `--force` resets back to `"local"` when no remote exists.

### Verification

After the fix, `claude-wiki init` (without `--force`) should update a stale lock file from:

```json
{ "repo_owner": "local", ... }
```

to:

```json
{ "repo_owner": "mrrobot0985", ... }
```

provided `git remote get-url origin` returns a parseable URL.

## Lazy migration strategy

### Philosophy

Migration should be **transparent and frictionless**. The user upgrades the package and the next normal command (`compile`, `query`, `lint`) detects the old layout, moves files atomically, and writes the new lock file. No explicit `migrate --to-v2` command.

### Detection criteria

`ConfigManager.load()` checks the loaded lock file for:

1. **Missing `layout_version`** or `layout_version == "1"`
1. **Legacy machine files in vault**
   - `kb_root / "state.json"` exists
   - `kb_root / "logs"` directory exists
   - `kb_root / "reports"` directory exists
1. **Legacy daily location**
   - `daily_dir` resolves to `repo_root / "daily"` when `kb_dir == "user"`

### Migration steps (all-or-nothing per artifact)

1. **Move machine files out of the vault**

   - `kb_root/state.json` → `~/.local/state/claude-wiki/repos/<owner>/<repo>/state.json`
   - `kb_root/logs/` → `~/.local/state/claude-wiki/repos/<owner>/<repo>/logs/`
   - `kb_root/reports/` → `~/.cache/claude-wiki/repos/<owner>/<repo>/reports/`
   - After successful move, `rmdir` empty legacy directories; if non-empty, log warning

1. **Move daily logs out of repo** (when `kb_dir == "user"`)

   - `repo_root/daily/` → `~/.local/share/claude-wiki-daily/<owner>/<repo>/`
   - Preserve timestamps and file content exactly

1. **Move vault to new namespace** (when `kb_dir == "user"`)

   - Old: `~/.local/share/claude-wiki/local/<repo>/` (stale `repo_owner: "local"`)
   - New: `~/.local/share/claude-wiki-vault/<owner>/<repo>/`
   - This is the riskiest step; abort if target already exists and is non-empty

1. **Rewrite lock file**

   - Set `layout_version: "2"`
   - Update `daily_dir` resolution to new default
   - Preserve user overrides (absolute/relative paths)

1. **Update registry**

   - Re-register with `GlobalIndexManager` using new paths

### Safety

- Every move uses a **temp file + `os.replace()` pattern** for files, and `shutil.move()` for directories.
- If any move fails, log a warning, leave source in place, and do not increment `layout_version`.
- Running twice: detects new paths already exist, skips cleanly.
- `reports_dir` in old lock file: ignored, not migrated. A deprecation warning is printed.

## Alternatives considered

- **Keep everything as-is** — rejected because the Obsidian graph and repo root are both polluted.
- **Put daily logs inside the vault under `~/.local/share/claude-wiki/daily/`** — rejected because Obsidian graphs every `.md` under the vault root; daily logs would create disconnected noise nodes.
- **Put machine files in `.claude/` regardless of mode** — rejected because user-wide mode should not touch the repo at all for operational artifacts.
- **Use Obsidian's folder exclusion settings to hide daily/machine directories** — rejected because exclusions are per-machine (stored in `.obsidian/app.json`), not portable across devices or reinstalls.
- **Separate knowledge repository (Option C)** — rejected as over-engineering for the current stage; the tool does not yet support a distillation pipeline that pushes decisions back into source repos.
