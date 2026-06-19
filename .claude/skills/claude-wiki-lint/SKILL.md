---
name: claude-wiki-lint
description: Run health checks on the knowledge base. Invoke with /claude-wiki-lint.
disable-model-invocation: true
---

# claude-wiki lint

Structural and LLM-based health checks for the KB.

## Trigger

- "lint the knowledge base"
- "check KB health"
- "find broken links"
- "run wiki lint"

## Process

1. Run `claude-wiki lint`
1. For structural-only (no LLM cost), add `--structural-only`
1. Completion: report printed or report file path shown.

## Checks

| Check           | Severity   | What it finds                                |
| --------------- | ---------- | -------------------------------------------- |
| Broken links    | Error      | `[[wikilinks]]` pointing to missing articles |
| Orphan pages    | Warning    | Articles with zero inbound links             |
| Orphan sources  | Warning    | Daily logs not yet compiled                  |
| Stale articles  | Warning    | Daily logs changed since last compile        |
| Sparse articles | Suggestion | Articles below 200 words                     |
| Contradictions  | Warning    | Cross-article conflicts (LLM-only)           |

## Flags

| Flag                | Purpose                                      |
| ------------------- | -------------------------------------------- |
| `--structural-only` | Skip LLM contradiction checks (free, faster) |

## Rules

- Reports are saved to `knowledge/reports/` (or the configured `reports_dir`) as `lint-YYYY-MM-DD.md`
- Structural checks are deterministic and free; contradiction checks cost ~$0.15–0.25
- Warnings do not fail the lint exit code; errors do

## Completion

- Terminal shows error/warning/suggestion counts
- Report path printed (e.g., `knowledge/reports/lint-2026-06-19.md`)
