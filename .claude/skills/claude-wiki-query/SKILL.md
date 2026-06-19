---
name: claude-wiki-query
description: Search and query the accumulated knowledge base. Invoke with /claude-wiki-query.
disable-model-invocation: true
---

# claude-wiki query

Ask the knowledge base natural-language questions.

## Trigger

- "search my KB"
- "what do I know about..."
- "ask the knowledge base"
- "query wiki"

## Process

1. Formulate the query as a single quoted string
1. Run `claude-wiki query "<question>"`
1. If user wants the answer saved back to KB, add `--file-back`
1. Completion: answer printed, and `--file-back` creates `qa/` article and updates `index.md`.

## Flags

| Flag          | Purpose                                                      |
| ------------- | ------------------------------------------------------------ |
| `--file-back` | Save the answer as a new `qa/` article and update `index.md` |

## Rules

- Queries are index-guided — the LLM reads `knowledge/index.md` first, then drills into relevant articles
- No RAG or vector search is used; retrieval relies on the human-maintained index and cross-links
- `--file-back` compounds knowledge: each saved answer becomes available to future queries

## Completion

- Answer printed to stdout with inline citations
- With `--file-back`: new article in `knowledge/qa/` and updated `index.md`
