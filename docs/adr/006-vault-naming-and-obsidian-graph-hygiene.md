# ADR-006: Vault Naming and Obsidian Graph Hygiene

## Status

Accepted

> Implemented in commit `4e66e53` and released in v0.4.0.

## Context

After implementing ADR-005, the global vault structure works but the Obsidian Graph view shows three distinct hygiene problems:

1. **Duplicate `index` nodes.** Every registered repository creates `index.md` inside its KB directory. Obsidian indexes all markdown files recursively and treats every `index.md` as the same node label "index". With three repos registered, the graph shows three disconnected "index" nodes that are impossible to tell apart.

1. **Broken cross-vault links.** `core.md` links to each per-repo index using absolute-path markdown links (`[display](/absolute/path/index.md)`). These are Markdown links, not Obsidian wikilinks, so the graph does not draw edges between `core` and the per-repo indices. The indices appear as orphaned floaters.

1. **Ghost `daily` nodes.** `core.md` renders daily log directories as markdown links (`[daily](/absolute/path/daily)`). Because the target is a directory, not a file, Obsidian creates a phantom "daily" node that has no content and no outgoing edges. Every repo adds another phantom, producing a cluster of disconnected "daily" nodes.

The root cause is a naming collision (`index.md` is generic) combined with link semantics (markdown links don't create graph edges) and directory links (directories aren't markdown files).

## Goals

1. Every repo catalog file has a unique, human-readable name in the graph.
1. `core.md` and per-repo catalog files have actual graph edges in Obsidian.
1. No phantom nodes for directories or non-file artifacts.
1. Existing articles inside a repo vault continue to link to their catalog without ambiguity.

## Decision

### 1. Per-repo catalog is `{repo_name}.md`, not `index.md`

Rename the master catalog from `index.md` to `{repo_name}.md` (e.g. `claude-wiki.md`, `my-project.md`).

Rationale:

- Unique basename means Obsidian graph nodes are instantly identifiable (`claude-wiki` vs `my-project` vs `index`).
- Articles inside the same vault can still wikilink to the catalog with `[[{repo_name}]]` because the file is in the same vault root.
- No collision when multiple repos are indexed inside a single global vault.

### 2. `core.md` uses wikilinks for cross-repo navigation

Replace absolute-path Markdown links with Obsidian wikilinks that include the relative vault path.

Before:

```markdown
- **KB index:** [mrrobot0985/claude-wiki/index.md](/home/.../claude-wiki/index.md)
- **Daily logs:** [daily](/home/.../daily)
```

After:

```markdown
- **KB index:** [[mrrobot0985/claude-wiki/claude-wiki|mrrobot0985/claude-wiki]]
- **Daily logs:** `~/.local/share/claude-wiki-daily/mrrobot0985/claude-wiki/`
```

Rationale:

- `[[...]]` wikilinks create graph edges in Obsidian.
- The `|` alias keeps the display text readable while the path resolves to the actual file.
- Daily logs are plain text (code-fenced or bare), eliminating phantom directory nodes.

### 3. No markdown links to directories

Any reference to a directory (daily logs, repo root, reports) is rendered as plain text or inline code, never as `[name](path)`.

Rationale:

- Directories are not markdown files; linking to them creates unresolvable graph nodes.
- Plain text still conveys the information without polluting the graph.

## Consequences

### Positive

- Graph view is immediately readable: one `core` node, one named node per repo, edges between them.
- No phantom `daily` or `index` floaters.
- Future repos automatically get unique catalog names without configuration.

### Negative

- Existing per-repo `index.md` files must be renamed and any wikilinks to `[[index]]` inside articles updated.
- `core.md` must be regenerated (via `compile` or manual edit) to pick up the new link format.
- Any external bookmarks or scripts hardcoded to `index.md` need updating.

## Migration

For each existing repo vault:

```bash
# Rename the catalog
mv index.md claude-wiki.md

# Update any wikilinks inside articles (if articles reference [[index]])
sed -i 's/\[\[index\]\]/[[claude-wiki]]/g' concepts/*.md connections/*.md qa/*.md
```

Then regenerate `core.md` by running `claude-wiki compile` or manually editing the global index.
