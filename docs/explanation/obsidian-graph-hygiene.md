# Obsidian Graph Hygiene

How `claude-wiki` keeps the Obsidian graph view readable when you scale to many repositories.

______________________________________________________________________

## The Problem

Obsidian’s graph view draws a node for **every markdown file** and an edge for **every wikilink** (`[[note]]`). This is powerful, but it has no concept of namespaces. When you point a single vault at multiple knowledge bases, three hygiene problems emerge.

### 1. Colliding Names

Every repo compiled by `claude-wiki` used to produce an `index.md` catalog. With five repos, the graph shows five nodes all labelled **index**. They are physically different files, but Obsidian collapses them by basename, so you cannot tell which repo each node belongs to.

### 2. Broken Cross-Vault Links

The global registry (`core.md`) linked to each per-repo catalog using standard Markdown links:

```markdown
- [mrrobot0985/claude-wiki](/home/.../claude-wiki/index.md)
```

Markdown links do **not** create graph edges. The per-repo catalogs appear as orphaned floaters with no connection to `core`.

### 3. Phantom Directory Nodes

Directory references were also rendered as Markdown links:

```markdown
- [daily](/home/.../daily)
```

Because `daily` is a folder, not a file, Obsidian creates an unresolvable phantom node. Every repo adds another phantom, producing a cluster of disconnected "daily" nodes that clutter the graph.

## The Design

ADR-006 introduced three rules that the compiler enforces automatically.

### Rule 1: Catalogs are Named After the Repository

Instead of `index.md`, the master catalog is `{repo_name}.md`:

| Repo              | Old catalog | New catalog          |
| ----------------- | ----------- | -------------------- |
| `claude-wiki`     | `index.md`  | `claude-wiki.md`     |
| `my-dotfiles`     | `index.md`  | `my-dotfiles.md`     |
| `experiment-2026` | `index.md`  | `experiment-2026.md` |

Now the graph shows `claude-wiki`, `my-dotfiles`, and `experiment-2026` as distinct, identifiable nodes. Inside each vault, articles wikilink to the catalog with `[[claude-wiki]]`, which resolves correctly because the file lives in the vault root.

### Rule 2: Cross-Vault Navigation Uses Wikilinks

`core.md` links to per-repo catalogs with Obsidian wikilinks that include the relative vault path:

```markdown
- **KB index:** [[mrrobot0985/claude-wiki/claude-wiki|mrrobot0985/claude-wiki]]
```

The portion before the `|` is the vault-resolved path; the portion after is the human-readable label. Obsidian draws an edge between `core` and `claude-wiki`, and the label stays short in reading view.

### Rule 3: Directories are Plain Text

Any reference to a directory is rendered as inline code or bare text, never as a link:

```markdown
- **Daily logs:** `~/.local/share/claude-wiki-daily/mrrobot0985/claude-wiki/`
```

No phantom node is created, because there is no `[]()` syntax for Obsidian tointerpret.

## How the Compiler Enforces It

During compilation, the LLM is instructed to:

1. Write the catalog as `{repo_name}.md`.
1. Use `[[wikilinks]]` for every internal article reference.
1. Cite daily logs as plain text (`- daily/YYYY-MM-DD.md - context`), never as `[[daily/…]]`.

The structural linter (`claude-wiki lint --structural-only`) verifies:

- No Markdown links target directories.
- Every `[[wikilink]]` resolves to an existing file.
- No duplicate basenames exist across the vault (detected via orphan analysis).

If a human manually edits an article and introduces a directory link or a dead wikilink, the next CI run catches it.

## Scaling to Many Repos

With these rules in place, a vault containing ten repos looks like this in graph view:

- One `core` node at the centre.
- Ten named repo nodes orbiting it, each connected by an edge from `core`.
- Dozens of concept and connection nodes inside each repo cluster, linked by wikilinks.
- **Zero** phantom daily nodes.
- **Zero** ambiguous index nodes.

The visual density is proportional to actual knowledge, not artifact count.

## Customisation Boundaries

If you add custom directories under the KB root (e.g. `people/`, `projects/`), the same hygiene rules apply:

- Give the directory a descriptive name.
- Reference files inside it with wikilinks (`[[people/alice]]`).
- Never link to the directory itself.

If you change `repo_name` in `.claude-wiki.lock`, run `claude-wiki rename-catalog` so the catalog filename stays in sync. Otherwise the graph will show both the old and new names until you clean up manually.

## Troubleshooting

| Symptom                        | Cause                            | Fix                                      |
| ------------------------------ | -------------------------------- | ---------------------------------------- |
| Two identically-named nodes    | Old `index.md` left after rename | Delete stale `index.md`, run `compile`   |
| Orphaned catalog floater       | `core.md` uses Markdown link     | Regenerate `core.md` via `compile`       |
| Cluster of "daily" phantoms    | Directory links in old articles  | Search/replace `[daily]` with plain text |
| Missing edge between two repos | Wikilink path wrong after move   | Check `core.md` paths match vault layout |

## Further Reading

- [ADR-006](../adr/006-vault-naming-and-obsidian-graph-hygiene.md) — formal decision record
- [How to migrate to user mode](../how-to/migrate-project-to-user-mode.md) — relocating the vault while preserving links
