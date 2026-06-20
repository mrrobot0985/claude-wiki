# ADR-007: No Wikilinks to Daily Logs

## Status

Accepted

> Implements the graph-hygiene rule that follows from ADR-005 and ADR-006.

## Context

ADR-005 placed daily logs **outside** the Obsidian vault
(`~/.local/share/claude-wiki-daily/<owner>/<repo>/`), separate from the compiled KB
(`~/.local/share/claude-wiki-vault/<owner>/<repo>/`). ADR-006 then fixed the graph
collapse caused by identical catalog basenames (`index.md`).

A related collapse remained: compiled concept/connection/qa articles cited their
source daily log as a wikilink, `- [[daily/YYYY-MM-DD.md]] - context`. Because the
daily log is not in the vault, that wikilink is dead. Worse, in a unified Obsidian
vault over the parent directory, every repository's `[[daily/2026-06-20.md]]`
resolves to the same single (missing) node, so articles across repos get linked to
the same daily log — exactly the ambiguous, cross-repo linkage ADR-006 set out to
prevent.

## Goals

- No dead `[[daily/…]]` links in compiled articles.
- No cross-repo graph collapse on the daily-log basename.
- Preserve per-article provenance for humans.

## Decision

Cite daily logs as **plain text only**, never as a `[[wikilink]]`:

- Article body `## Sources` section: `- daily/YYYY-MM-DD.md - context` (no brackets).
- Frontmatter `sources:` list: retained as YAML metadata (Obsidian renders
  frontmatter as properties, not graph nodes, so it is not a pollutant).
- Catalog "Compiled From" column and `log.md` build-log lines: plain text, unchanged.

The `compile` template and prompt were aligned with `query`, which already rendered
`daily/` citations as plain text.

### Rejected: rename daily logs to `YYYY-MM-DD-{repo}.md`

This would make basenames unique, but it does not fix the failure: daily logs remain
outside the vault, so the wikilink is still dead. It disambiguates a per-repo
directory that is already namespaced by `<owner>/<repo>`. Solves a hypothetical, not
the current failure (anti-overengineering §2).

## Consequences

- New compilations emit no `[[daily/…]]` wikilinks.
- Existing articles migrated once (brackets stripped to plain text).
- `lint` is unaffected: it already skipped `daily/` targets in its broken-wikilink
  check, and its uncompiled-log check reads compile state, not frontmatter `sources:`.
- Provenance is retained as plain text in three places (article body, frontmatter,
  catalog, build log) — readable by humans, invisible to the graph.

## Migration

One-time strip of `[[daily/…]]` → `daily/…` across existing article bodies in each
vault. The template change prevents recurrence.
