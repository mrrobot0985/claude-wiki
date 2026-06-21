# Knowledge Base Schema

## `knowledge/{repo_name}.md`

Master catalog table:

| Article                | Summary          | Compiled From       | Updated    |
| ---------------------- | ---------------- | ------------------- | ---------- |
| \[[concepts/example]\] | One-line summary | daily/YYYY-MM-DD.md | YYYY-MM-DD |

## Concept articles (`knowledge/concepts/`)

```markdown
---
title: "Concept Name"
aliases: [alias]
tags: [tag]
sources:
  - "daily/YYYY-MM-DD.md"
created: YYYY-MM-DD
updated: YYYY-MM-DD
---

# Concept Name

Core explanation.

## Key Points

- Bullet point

## Details

Deeper explanation.

## Related Concepts

- [[concepts/related]] - connection note

## Sources

- daily/YYYY-MM-DD.md - context
```

Daily logs live outside the Obsidian vault (ADR-007), so cite them as **plain text,
never a `[[wikilink]]`** — a `[[daily/…]]` link is dead and, across repos, collapses
to the same missing graph node.

## Connection articles (`knowledge/connections/`)

Link two or more concepts and explain the non-obvious relationship.

## Q&A articles (`knowledge/qa/`)

Filed by `claude-wiki query --file-back` to persist a question and its answer as a compounding knowledge article. One file per question, slugged from the question text.

```yaml
---
title: "Q: <the question>"
question: "<the question>"
consulted:
  - "concepts/x"
  - "connections/y"
filed: YYYY-MM-DD
---
```

The body has an `## Answer`, a `## Sources Consulted` list, and a `## Follow-Up Questions` prompt. `lint` applies its frontmatter checks to `qa/` just as it does to `concepts/` and `connections/`.

## Build log (`knowledge/log.md`)

```markdown
## [YYYY-MM-DDTHH:MM:SS] compile | daily/YYYY-MM-DD.md
- Source: daily/YYYY-MM-DD.md
- Articles created: [[concepts/x]]
- Articles updated: (none)
```
