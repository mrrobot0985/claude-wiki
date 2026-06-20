# Use Tags

Tag articles so you can browse, query, and audit the knowledge base by topic.

______________________________________________________________________

## Add Tags to an Article

Tags live in the YAML frontmatter of any article under `knowledge/concepts/`,
`knowledge/connections/`, or `knowledge/qa/`:

```markdown
---
title: "OAuth 2.0 Flows"
tags: [oauth, security, api]
sources:
  - "daily/2026-06-20.md"
---
```

Use lowercase, hyphenated tag names. Tags are a plain YAML list; the compiler
copies them from daily logs or you can add them by hand.

## List Every Tag in the Knowledge Base

```bash
claude-wiki tags
```

Human output prints three aligned columns:

```text
tag       count  example
oauth        12  concepts/oauth-2-flows.md
security      7  concepts/rbac.md
api           3  connections/api-rate-limiting.md
```

For machine-readable output, use `--json`:

```bash
claude-wiki tags --json
```

```json
[
  {
    "tag": "oauth",
    "count": 12,
    "examples": [
      "concepts/oauth-2-flows.md",
      "concepts/pkce.md",
      "qa/2026-06-20-token-lifetime.md"
    ]
  }
]
```

An empty knowledge base prints a clear message and exits non-zero.

## Query by Tag

Restrict a query to articles tagged with a specific name:

```bash
claude-wiki query "How do refresh tokens work?" --tag oauth
```

Pass `--tag` more than once to take the union of several tags:

```bash
claude-wiki query "Compare JWT and session cookies" --tag oauth --tag security
```

When multiple scope flags are present they combine by AND, so `--tag oauth --tag security` only returns articles that have *both* tags.

## Interpret `tag_single_use` Lint Suggestions

`claude-wiki lint` flags tags that appear on exactly one article:

```text
[?] `concepts/rare-topic.md` - Tag 'rare-topic' appears on only one article - possible typo or orphan tag
```

This is a **suggestion**, not an error. It usually means one of three things:

1. **Typo** — the tag was meant to match an existing tag (`oath` vs `oauth`).
1. **Orphan** — the topic is real but has not been written about elsewhere yet.
1. **Intentional** — a one-off label such as `archive` or `draft`.

Fix typos by editing the article frontmatter. For intentional single-use tags,
suppress the suggestion with `.claude-wiki-lint-ignore` (see
[Suppress Lint False Positives](suppress-lint-false-positives.md)).
