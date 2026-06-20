# Scope Queries

Narrow a query so the answer draws from only the articles that matter.

______________________________________________________________________

## Available Scope Flags

```bash
claude-wiki query "QUESTION" \
  --category concepts \
  --tag rust \
  --tag async \
  --since 2026-01-01 \
  --max-chars 12000
```

| Flag          | What it filters                                          |
| ------------- | -------------------------------------------------------- |
| `--category`  | Article subdirectory: `concepts`, `connections`, or `qa` |
| `--tag`       | YAML frontmatter tag (repeatable)                        |
| `--since`     | Article `updated` or `created` date, `YYYY-MM-DD`        |
| `--max-chars` | Total context budget; oldest articles dropped first      |

## Composition Rules

Scope filters compose by **AND across flag types**, **union within repeated
flags**:

- `--category concepts --tag rust` only returns concept articles tagged `rust`.
- `--tag rust --tag async` returns articles tagged `rust` **or** `async`.
- `--category concepts --category connections` returns articles from either
  directory.
- `--since 2026-01-01 --max-chars 8000` returns articles dated 2026-01-01 or
  later, then trims the oldest ones until the total fits in 8,000 characters.

## Filter by Category

Limit the query to one or more KB subdirectories:

```bash
claude-wiki query "How does authentication work?" --category concepts
claude-wiki query "Compare auth patterns" --category concepts --category connections
```

## Filter by Tag

Tags are matched against the YAML frontmatter list. Repeat `--tag` for a union:

```bash
claude-wiki query "Explain concurrency in Rust" --tag rust --tag async
```

This is equivalent to "articles tagged `rust` or `async`".

See [Use Tags](use-tags.md) for how to add tags and list the tag inventory.

## Filter by Date

Only include articles created or updated on or after the given date:

```bash
claude-wiki query "What changed this quarter?" --since 2026-04-01
```

Articles without `created` or `updated` frontmatter dates are always included,
so the query never silently drops undated legacy content.

## Cap Context with `--max-chars`

Large knowledge bases can exceed the LLM context window. Set a budget and the
oldest articles are dropped first:

```bash
claude-wiki query "Summarise the project" --max-chars 20000
```

The catalog (`{repo_name}.md`) is always loaded and does not count toward the
budget, so the query still sees the article index even when articles are
trimmed.

## Empty-Scope Behavior

If no article matches the combined scope, the command prints a clear message
and exits `1`:

```text
No articles matched the requested scope.
```

With `--json` the same message appears in the `answer` field and `citations` is
empty, so scripts can handle the case without parsing stderr.

## Combining Scope with `--file-back`

Scope flags apply to the query only. If you also pass `--file-back`, the
resulting Q&A article is filed into `knowledge/qa/` regardless of the scope:

```bash
claude-wiki query "Rust async recap" --tag rust --file-back
```
