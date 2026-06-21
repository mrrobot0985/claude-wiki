# Inspect Knowledge-Base Topology with `graph`

Use `claude-wiki graph` to see the shape of your knowledge base at a glance —
how articles connect, which are orphaned, which are hubs, and whether the graph
is fragmented. It is read-only and costs nothing (no LLM call).

## Run the report

```bash
claude-wiki graph
```

```text
claude-wiki graph for my-repo

Articles: 42 (30 concepts, 7 connections, 5 qa)
Links:    58

Orphans: 3
  concepts/abandoned-draft
  concepts/one-off-note
  qa/old-question

Hubs (top 5 by inbound links):
  concepts/vault-layout (12 inbound)
  concepts/adr-005-directory-redesign (8 inbound)
  concepts/catalog-naming (6 inbound)

Components: 2 connected, largest size 39
```

## Read the report

- **Articles / Links** — overall size and how densely linked the KB is. A young
  KB naturally has few links; a mature one with a low links-to-articles ratio may
  be under-connected.
- **Orphans** — articles with zero inbound links: nothing else in the KB links to
  them. These overlap with `lint`'s `orphan_page` warning. An orphan is not
  necessarily bad — a standalone reference may be intentionally self-contained —
  but a growing orphan count usually means drafts piling up or forgotten notes.
- **Hubs** — the most-referenced articles (by inbound link count). These are the
  conceptual centers of the KB; they are also the most-read, so they are the
  highest-leverage places to invest in clarity and accuracy.
- **Components** — connected groups when links are treated as undirected. A
  single component means the whole KB is reachable from any article. A count
  above one means the KB has fragmented into disconnected clusters that nothing
  bridges.

## Act on what you find

- **Orphans**: link them from a related article or from the catalog, or remove
  them if they are obsolete. `claude-wiki lint` will flag the same articles as
  `orphan_page`; resolve once and both reports improve.
- **Fragmentation (components > 1)**: write `connections/` articles that bridge
  the clusters — that is exactly what the `connections/` category is for.
- **Hubs**: keep hub articles accurate and well-linked; since many articles
  depend on them, a hub with a stale claim propagates error widely.

## Automate it

For CI, dashboards, or tracking drift over time, use JSON:

```bash
claude-wiki graph --json | jq '{articles, links, components: .components.count, orphans: (.orphans | length)}'
```

See [Use JSON Output in CI and Scripts](use-json-output.md#graph-json) for the
full schema and exit-code contract. A rising `orphans` count or a growing
`components` count signals a knowledge base drifting apart — surface it in a PR
comment or a dashboard.

## Options

| Flag       | Purpose                                            |
| ---------- | -------------------------------------------------- |
| `--top N`  | Number of hubs to list (default `5`; positive int) |
| `--json`   | Machine-readable JSON instead of the human report  |
| `--path P` | Repo root (default: auto-detect from cwd)          |

`graph` exits `0` on success, `1` if not in a git repository or no KB directory
exists. See the [CLI reference](../reference/cli.md) for the authoritative flag
list.
