# Knowledge Base Schema

## `knowledge/index.md`

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

- [[daily/YYYY-MM-DD.md]] - context
```

## Connection articles (`knowledge/connections/`)

Link two or more concepts and explain the non-obvious relationship.

## Build log (`knowledge/log.md`)

```markdown
## [YYYY-MM-DDTHH:MM:SS] compile | daily/YYYY-MM-DD.md
- Source: daily/YYYY-MM-DD.md
- Articles created: [[concepts/x]]
- Articles updated: (none)
```
