# Implementation Plan — ADR-006: Vault Naming and Obsidian Graph Hygiene

> **Status: Completed.** Released in v0.4.0 (commits `4e66e53`, `3865422`). This document is preserved for historical reference.

## Goal

Execute issues #32–#37 as a single atomic branch so `main` never contains mismatched catalog names. After merge, every per-repo knowledge base uses `{repo_name}.md` as its catalog, `core.md` emits Obsidian wikilinks instead of absolute markdown links, and directory references are plain text.

## Decisions from Refinement

1. **Atomic branch.** #32–#35 and #37 land together in one CI-passing PR. #36 (local vault migration) runs after the new code is installed.
1. **No symlink shim.** Rejected as maintenance burden. SessionStart hook gets a temporary fallback to `index.md` (silent fallback; deprecation warning deferred to a future release).
1. **Wikilink format.** `[[owner/repo/repo-name|repo-name]]` — the alias keeps display text short.
1. **Plain-text directories.** Daily logs and repo root rendered as inline code (`` `path` ``), never as markdown links.
1. **Dedicated migration command.** `claude-wiki rename-catalog` with dry-run, idempotency, and alias/heading-safe wikilink rewriting.
1. **MigrationManager also renames.** When `_migrate_dir` moves a KB directory, it renames `index.md` to `{repo_name}.md` and rewrites article wikilinks inside the moved tree.

______________________________________________________________________

## Execution Order

| Step | Issue | Work                                                        | Files                                                                                                                                                          |
| ---- | ----- | ----------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1    | #32   | Rename per-repo catalog from `index.md` to `{repo_name}.md` | `global_index.py`, `query.py`, `lint.py`, `AGENTS.md`, tests                                                                                                   |
| 2    | #34   | Convert `core.md` links to Obsidian wikilinks               | `global_index.py:_generate_markdown`                                                                                                                           |
| 3    | #33   | Remove directory markdown links from `core.md`              | `global_index.py:_generate_markdown`                                                                                                                           |
| 4    | #35   | Update SessionStart hook to inject renamed catalog          | `session_start.py`                                                                                                                                             |
| 5    | #37   | Update tests for new naming and link conventions            | `test_compile.py`, `test_global_index.py`, `test_session_start.py`, `test_query.py`, `test_lint.py`, `test_integration.py`, `test_cli.py`, `test_migration.py` |
| 6    | —     | Add `claude-wiki rename-catalog` command                    | `commands/rename_catalog.py`                                                                                                                                   |
| 7    | —     | Update MigrationManager to rename during directory moves    | `migration.py`                                                                                                                                                 |
| 8    | #36   | Migrate existing local vaults                               | Manual / `rename-catalog` command                                                                                                                              |
| 9    | #31   | Close parent tracking issue after migration verified        | —                                                                                                                                                              |

______________________________________________________________________

## Step 1 — Rename Catalog File (#32)

### `src/claude_wiki/global_index.py`

**Line 138** (`_generate_markdown`):

```python
# BEFORE
idx_link = self._format_link(kb_root / "index.md")

# AFTER
idx_link = self._format_link(kb_root / f"{e.repo_name}.md")
```

Note: `_format_link` is still needed for backward compatibility display, but wikilink generation (Step 2) will replace the markdown link syntax.

### `src/claude_wiki/commands/query.py`

**Line 140** (`_read_kb_content`):

```python
# BEFORE
index_file = kb_root / "index.md"

# AFTER
index_file = kb_root / f"{config.repo_name}.md" if config else kb_root / "index.md"
```

Problem: `_read_kb_content` does not receive `config`. Options:

- (a) Add an optional `repo_name` parameter, callers pass it.
- (b) Read `repo_name` from the directory name if in XDG layout (fragile).
- (c) Look for both `{dir_name}.md` and `index.md`.

Decision: **(a)** — add `repo_name: str | None = None` parameter. `_handle_query` passes `config.repo_name`. This is clean and deterministic.

**Line 232** (`_update_index`):

```python
# BEFORE
index_file = kb_root / "index.md"

# AFTER
index_file = _resolve_catalog_file(kb_root)
```

Add helper `_resolve_catalog_file(kb_root: Path) -> Path` that checks if the KB root's directory name matches a `{name}.md` file (heuristic for when `repo_name` is not available), falling back to `index.md`. However, `_update_index` is called from `_file_back` which is called from `_handle_query`, so `repo_name` is available. Pass `repo_name` through the call chain.

Actually, simpler: `_update_index` and `_append_log` are called inside `_file_back` which has access to `kb_root` but not `repo_name`. The cleanest approach is to resolve the catalog file by looking for exactly one `{something}.md` at the KB root that isn't a subdirectory, or accept that `_file_back` needs `repo_name`.

Better approach: introduce a small utility `_resolve_catalog(kb_root: Path, repo_name: str | None = None) -> Path`:

- If `repo_name` given, return `kb_root / f"{repo_name}.md"`.
- Else, try to infer from existing files: if `index.md` exists and no `{name}.md` exists, return `index.md` (backward compat).
- If exactly one `{name}.md` exists, return it.
- Otherwise, return `kb_root / "index.md"` as default.

### `src/claude_wiki/commands/lint.py`

**Line 333** (`_read_all_wiki_content`):

```python
# BEFORE
index_file = kb_root / "index.md"

# AFTER
index_file = kb_root / "index.md"  # lint does not know repo_name here
# Need to resolve catalog file similarly to query
```

`lint.py`'s `_lint_handler` has access to `config` via `ConfigManager.load()`. Pass `config.repo_name` into `_read_all_wiki_content` and `_run_llm_checks`.

### `src/claude_wiki/AGENTS.md`

**Line 3**:

```markdown
# BEFORE
## `knowledge/index.md`

# AFTER
## `knowledge/{repo_name}.md`
```

______________________________________________________________________

## Step 2 — Wikilinks in `core.md` (#34)

### `src/claude_wiki/global_index.py`

Rewrite `_generate_markdown` lines 131–157.

**Before:**

```python
lines.append(f"- **KB index:** [{e.repo_owner}/{e.repo_name}/index.md]({idx_link})")
```

**After:**

```python
lines.append(
    f"- **KB index:** [[{e.repo_owner}/{e.repo_name}/{e.repo_name}|{e.repo_name}]]"
)
```

The wikilink path must be relative to the global vault root so Obsidian resolves it. The global vault root is `self.base_dir` (e.g., `~/.local/share/claude-wiki-vault/`). Each KB is at `self.base_dir / owner / repo_name /`. So the relative path from the vault root to the catalog is `owner/repo_name/repo_name.md`. Obsidian wikilink syntax: `[[owner/repo_name/repo_name|display]]`.

However, `_generate_markdown` does not currently know the relative path from `self.base_dir` to `kb_root`. We need to compute it or store it. Since `kb_root` is already an absolute path and `self.base_dir` is known:

```python
vault_rel = Path(e.kb_root).relative_to(self.base_dir)
catalog_name = f"{e.repo_name}.md"
wikilink = f"[[{vault_rel / catalog_name}|{e.repo_name}]]"
```

**Edge case:** if `kb_root` is not under `self.base_dir` (e.g., project-mode KB not inside the global vault), the relative path computation fails. In that case, fall back to plain text (no link) since cross-vault wikilinks won't resolve anyway. This addresses the high-severity risk from the refinement.

```python
try:
    vault_rel = Path(e.kb_root).relative_to(self.base_dir)
    idx_wikilink = f"[[{vault_rel / e.repo_name}|{e.repo_name}]]"
except ValueError:
    idx_wikilink = f"{e.repo_owner}/{e.repo_name}"
```

______________________________________________________________________

## Step 3 — Remove Directory Markdown Links (#33)

### `src/claude_wiki/global_index.py`

In `_generate_markdown`, replace repo root and daily log links with inline code.

**Lines 148–154 before:**

```python
if e.repo_root is not None:
    root_path = Path(e.repo_root)
    root_link = self._format_link(root_path)
    daily_dir = self._get_daily_dir(root_path)
    daily_link = self._format_link(daily_dir)
    lines.append(f"- **Repo root:** [{root_path.name}]({root_link})")
    lines.append(f"- **Daily logs:** [{daily_dir.name}]({daily_link})")
```

**After:**

```python
if e.repo_root is not None:
    root_path = Path(e.repo_root)
    daily_dir = self._get_daily_dir(root_path)
    lines.append(f"- **Repo root:** `{root_path.resolve()}`")
    lines.append(f"- **Daily logs:** `{daily_dir.resolve()}`")
```

Remove `_format_link` usage entirely from `_generate_markdown` since wikilinks and plain text don't need it. Keep `_format_link` as a public method for backward compatibility or remove it if unused elsewhere. Check callers.

______________________________________________________________________

## Step 4 — SessionStart Hook Update (#35)

### `src/claude_wiki/hook_handlers/session_start.py`

**Line 36–41 (`_get_kb_index`):**

Add temporary backward-compatible fallback.

```python
def _get_kb_index(kb_root: Path, repo_name: str) -> str:
    """Read knowledge/{repo_name}.md if it exists, falling back to index.md."""
    primary = kb_root / f"{repo_name}.md"
    if primary.exists():
        return primary.read_text(encoding="utf-8")
    legacy = kb_root / "index.md"
    if legacy.exists():
        # deprecation warning can be logged; for hook output we just read it
        return legacy.read_text(encoding="utf-8")
    return "(empty - no articles compiled yet)"
```

**Line 76–78 (`_build_context`):**
Pass `config.repo_name` into `_get_kb_index`.

```python
index = _get_kb_index(kb_root, config.repo_name)
```

Remove the temporary fallback in a follow-up release (issue to file separately).

______________________________________________________________________

## Step 5 — Test Updates (#37)

### `tests/test_compile.py`

- **Line 185** (`fake_compile`): rename `index.md` to `my-project.md` (from `config.repo_name` which is `my-project` in `_make_repo`).
- **Line 205**: `index_path = kb_root / "my-project.md"`
- **Lines 320–323** (`test_read_index_exists`): rename test to `test_read_index_exists_with_repo_name`, create `my-project.md` instead of `index.md`, call `_read_index(kb, "my-project")`.

Note: `_read_index` signature is `_read_index(kb_root: Path, repo_name: str)`. Tests must pass `repo_name`.

### `tests/test_global_index.py`

- **Line 154** (`test_generated_markdown_links_to_index`): change assertion from `str(kb / "index.md")` to check for wikilink format `[[local/my-repo/my-repo|my-repo]]` instead of absolute path.
- **Line 432** (`test_generate_markdown_uses_absolute_paths`): this test specifically checks absolute path links. It should now check for wikilink format (or plain text for out-of-vault KBs). Since the KB in this test may not be under `base_dir`, the behavior is: if KB is inside `base_dir`, wikilink; else plain text. Set up the test with KB under `base_dir / owner / repo_name /`.
- **Lines 459, 471**: similar updates.
- **Lines 146–157**: rewrite to verify wikilinks and plain-text directories.
- All tests that check `str(repo.resolve())` or `str(daily.resolve())` in `core.md` should now check for backtick-wrapped paths instead of markdown links.

### `tests/test_session_start.py`

- All `index.md` creations become `{repo_name}.md` (where `repo_name` is typically `repo` in the test fixtures).
- **Line 45**: `(kb / "repo.md").write_text(...)` instead of `(kb / "index.md")`.
- Update all similar occurrences.

### `tests/test_query.py`

- All `index.md` creations become `repo.md` (or whatever `repo_name` is in the test fixture).
- `_read_kb_content` calls now may need `repo_name` passed; update call sites in tests.

### `tests/test_lint.py`

- All `index.md` creations become `repo.md`.
- `_read_all_wiki_content` signature change propagated.

### `tests/test_integration.py`

- Fake `compile` command creates `index.md` — change to create `{repo_name}.md`.
- Fake `query` and `lint` commands reference `index.md` — change to `{repo_name}.md`.

### `tests/test_cli.py`

- Line 473: `index.md` → `repo.md` (or appropriate repo_name).
- Line 490: `index.md` → `repo.md`.

### `tests/test_migration.py`

- All `index.md` references inside KB directories become `test.md` or the relevant `repo_name`. The tests create `ProjectConfig(repo_name="test")` so the catalog would be `test.md`.
- Note: MigrationManager itself needs to handle renaming (see Step 7), so tests for migration will also test that `index.md` is renamed to `{repo_name}.md` during moves.

______________________________________________________________________

## Step 6 — `claude-wiki rename-catalog` Command

### New file: `src/claude_wiki/commands/rename_catalog.py`

A first-class migration command that renames `index.md` to `{repo_name}.md` and rewrites `[[index]]` wikilinks inside articles.

```python
def _rename_catalog(kb_root: Path, repo_name: str, *, dry_run: bool = False) -> list[str]:
    """Rename index.md to {repo_name}.md and rewrite article wikilinks.

    Returns a list of human-readable action descriptions.
    """
    actions: list[str] = []
    legacy = kb_root / "index.md"
    primary = kb_root / f"{repo_name}.md"

    if not legacy.exists():
        if primary.exists():
            actions.append(f"Catalog already named {primary.name} — nothing to do.")
            return actions
        actions.append(f"No index.md found in {kb_root} — nothing to rename.")
        return actions

    if primary.exists():
        actions.append(f"ERROR: {primary.name} already exists — refusing to overwrite.")
        return actions

    # Rename catalog
    if dry_run:
        actions.append(f"[dry-run] Would rename {legacy.name} -> {primary.name}")
    else:
        legacy.rename(primary)
        actions.append(f"Renamed {legacy.name} -> {primary.name}")

    # Rewrite wikilinks in articles
    for subdir_name in ("concepts", "connections", "qa"):
        subdir = kb_root / subdir_name
        if not subdir.exists():
            continue
        for article in subdir.glob("*.md"):
            content = article.read_text(encoding="utf-8")
            # Replace [[index]] and [[index|...]] with [[repo_name|...]]
            new_content = _rewrite_index_wikilinks(content, repo_name)
            if new_content != content:
                if dry_run:
                    actions.append(
                        f"[dry-run] Would rewrite wikilinks in {article.relative_to(kb_root)}"
                    )
                else:
                    article.write_text(new_content, encoding="utf-8")
                    actions.append(
                        f"Rewrote wikilinks in {article.relative_to(kb_root)}"
                    )

    return actions


def _rewrite_index_wikilinks(content: str, repo_name: str) -> str:
    """Replace [[index]] and [[index|alias]] with [[repo_name]] and [[repo_name|alias]].

    Preserves [[index#heading]] as [[repo_name#heading]].
    """
    import re

    def replacer(match: re.Match[str]) -> str:
        inner = match.group(1)
        # Handle alias
        if "|" in inner:
            parts = inner.split("|", 1)
            if parts[0] == "index" or parts[0].startswith("index#"):
                new_target = parts[0].replace("index", repo_name, 1)
                return f"[[{new_target}|{parts[1]}]]"
            return match.group(0)
        # No alias
        if inner == "index" or inner.startswith("index#"):
            new_target = inner.replace("index", repo_name, 1)
            return f"[[{new_target}]]"
        return match.group(0)

    return re.sub(r"\[\[([^\]]+)\]\]", replacer, content)
```

Register as a CLI command with `--dry-run` and `--path` flags.

______________________________________________________________________

## Step 7 — MigrationManager Renames During Directory Moves

### `src/claude_wiki/migration.py`

After `_migrate_dir` successfully moves a KB directory (label == "kb_dir"), post-process the destination to rename `index.md` to `{repo_name}.md` and rewrite article wikilinks.

Modify `check_and_migrate` to pass `repo_name` into `_migrate_dir` or perform the rename after the move in `check_and_migrate` itself.

```python
# In check_and_migrate, after the kb_dir move:
if kb_changed and result.migrated and not result.errors and not dry_run:
    _post_process_kb_rename(new_kb, current.repo_name)
```

Add `_post_process_kb_rename(kb_root: Path, repo_name: str) -> None` that calls the same logic as the rename-catalog command (extract shared logic into a module-level utility).

Since both `rename_catalog.py` and `migration.py` need the wikilink rewriting logic, extract `_rewrite_index_wikilinks` and the catalog renaming logic into a shared module. Options:

- `claude_wiki/catalog_utils.py` — small utility module
- `claude_wiki/migration.py` exports the helper, `rename_catalog.py` imports it

Decision: shared logic lives in `claude_wiki/catalog_utils.py` (`resolve_catalog`, `rewrite_index_wikilinks`), imported by both `rename_catalog.py` and `migration.py`.

______________________________________________________________________

## Step 8 — Local Vault Migration (#36)

For the user's local `claude-wiki` repository:

```bash
# From the repo root
uv run claude-wiki rename-catalog --dry-run
uv run claude-wiki rename-catalog
uv run claude-wiki compile  # regenerates core.md
```

Then verify in Obsidian that:

1. The per-repo catalog is named `claude-wiki` in the graph.
1. `core.md` has an edge to `claude-wiki`.
1. No phantom `daily` nodes exist.

______________________________________________________________________

## Risk Register

| #   | Risk                                                                                                             | Severity | Mitigation                                                                                                                |
| --- | ---------------------------------------------------------------------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------------------------------------- |
| 1   | Project-mode KBs not under global vault root break wikilink resolution in `core.md`                              | High     | `_generate_markdown` falls back to plain text when `kb_root` is not under `base_dir`; add test for this case              |
| 2   | `query.py` and `lint.py` index resolution without `config` parameter breaks in code paths that don't load config | Medium   | `_resolve_catalog` helper with graceful fallback to `index.md` when `repo_name` unavailable                               |
| 3   | Tests with hardcoded `index.md` may be missed during mass update                                                 | Medium   | Run `grep -rn 'index\.md' tests/` before final commit; add CI check if needed                                             |
| 4   | SessionStart hook backward-compat fallback never gets removed                                                    | Low      | File follow-up issue to remove fallback in v0.5.0                                                                         |
| 5   | `rename-catalog` command corrupts `[[index\|alias]]` or `[[index#heading]]`                                      | Medium   | Unit tests for `_rewrite_index_wikilinks` covering all variants; regex is anchored and only replaces exact "index" prefix |

______________________________________________________________________

## Acceptance Criteria (Whole Branch)

- [x] `compile.py` LLM prompt references `{repo_name}.md`
- [x] `global_index.py` generates wikilinks `[[owner/repo/repo-name|repo-name]]` for KB index references
- [x] `global_index.py` renders repo root and daily log paths as inline code, never markdown links
- [x] `session_start.py` reads `{repo_name}.md`, falling back to `index.md` with no crash
- [x] `query.py` reads and updates `{repo_name}.md` instead of `index.md`
- [x] `lint.py` reads `{repo_name}.md` instead of `index.md`
- [x] `AGENTS.md` schema references `knowledge/{repo_name}.md`
- [x] All 354 tests pass with updated expectations
- [x] `rename-catalog` command exists with `--dry-run`, renames `index.md` and rewrites `[[index]]` wikilinks
- [x] `MigrationManager` renames catalog during kb_dir moves
- [x] End-to-end integration test passes: init → compile → query → lint with new naming
- [x] CI green: ruff, mypy --strict, pytest, mdformat --check

______________________________________________________________________

## Open Questions

1. Should `rename-catalog` also regenerate `core.md` automatically? Synthesis suggests yes; add a call to `GlobalIndexManager.register(...)` or `GlobalIndexManager()._index_path().write_text(...)` after rename.
1. Should `_resolve_catalog` in `query.py`/`lint.py` prefer the directory-name heuristic when `repo_name` is absent? Decision: yes, but log a warning so the user knows inference happened.

______________________________________________________________________

## Estimated Effort

- Code changes: 8 files, ~60 lines modified
- Test updates: 8 test files, ~100 lines modified
- New command: 1 file, ~80 lines
- Shared utility: 1 file, ~30 lines
- Total: ~270 lines across 18 files; 1–2 hours implementation, 30 minutes verification
