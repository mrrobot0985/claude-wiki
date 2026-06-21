# Use JSON Output in CI and Scripts

Parse `claude-wiki` output reliably in automation.

______________________________________________________________________

## Commands That Support `--json`

| Command              | `--json` output                                  |
| -------------------- | ------------------------------------------------ |
| `claude-wiki query`  | Answered question + cited articles               |
| `claude-wiki lint`   | Structured list of issues                        |
| `claude-wiki status` | Repository health checks with per-check status   |
| `claude-wiki graph`  | Link topology: orphans, hubs, components, counts |
| `claude-wiki tags`   | Tag inventory with counts and examples           |

Human-readable output is optimized for reading; JSON output is optimized for
piping into `jq`, GitHub Actions, or custom scripts.

## Query JSON

```bash
claude-wiki query "What is the vault layout?" --json
```

```json
{
  "answer": "Project mode stores the KB at ...",
  "citations": [
    "concepts/vault-layout",
    "explanation/obsidian-graph-hygiene"
  ]
}
```

`citations` is a list of article paths as they appear inside wikilinks, without
`.md` extensions. Confidence is intentionally omitted: the current
implementation does not compute a meaningful score, so emitting `0.0` would be
misleading.

### Exit-code contract for `query --json`

| Code | Meaning                                               | JSON payload                                     |
| ---- | ----------------------------------------------------- | ------------------------------------------------ |
| `0`  | Answer produced                                       | `{answer, citations}`                            |
| `1`  | Empty knowledge base or no articles matched the scope | `{"answer": "...", "citations": []}`             |
| `2`  | Usage error or `claude-agent-sdk` unavailable         | `{"answer": "<error message>", "citations": []}` |

A non-zero exit code still prints valid JSON, so callers can parse the result
before deciding how to react.

## Lint JSON

```bash
claude-wiki lint --json
```

```json
{
  "issues": [
    {
      "severity": "error",
      "file": "concepts/broken-example.md",
      "check": "broken_link",
      "message": "Broken link: [[missing-target]] - target does not exist"
    },
    {
      "severity": "warning",
      "file": "concepts/orphan.md",
      "check": "orphan_page",
      "message": "Orphan page: no other articles link to [[concepts/orphan]]"
    }
  ]
}
```

### Exit-code contract for `lint --json`

| Code | Meaning                                                         |
| ---- | --------------------------------------------------------------- |
| `0`  | Clean, or warnings present without `--fail-on-warning`          |
| `1`  | Warnings present and `--fail-on-warning` was passed             |
| `2`  | Errors present, or the command was run outside a git repository |

Use `--fail-on-warning` when you want a CI gate to fail on any warning:

```bash
claude-wiki lint --json --fail-on-warning
```

## Status JSON

```bash
claude-wiki status --json
```

```json
{
  "repo": "my-repo",
  "total_errors": 1,
  "checks": [
    {"name": "Lock file", "status": "ok", "message": ".claude-wiki.lock present and valid", "errors": 0},
    {"name": "Hooks", "status": "error", "message": "claude-wiki hooks not found in settings", "errors": 1}
  ]
}
```

Each check has a `status` of `"ok"`, `"warning"`, or `"error"` (`"error"` when `errors > 0`,
`"warning"` when the check passed with a caveat, else `"ok"`). The leading status icon is
stripped from `message`.

### Exit-code contract for `status --json`

| Code | Meaning                                          | JSON payload                                         |
| ---- | ------------------------------------------------ | ---------------------------------------------------- |
| `0`  | All checks passed (`total_errors == 0`)          | `{repo, total_errors, checks}`                       |
| `1`  | One or more checks errored, or not in a git repo | `{repo, total_errors, checks}` or `{"error": "..."}` |

## Graph JSON

```bash
claude-wiki graph --json
```

```json
{
  "repo": "my-repo",
  "articles": 42,
  "by_subdir": {"concepts": 30, "connections": 7, "qa": 5},
  "links": 58,
  "orphans": ["concepts/unused-concept"],
  "hubs": [{"article": "concepts/vault-layout", "inbound": 12}],
  "components": {"count": 3, "largest": 38}
}
```

`links` counts outbound `[[wikilinks]]` that resolve to an existing article. `orphans` are
articles with zero inbound links (consistent with lint's `orphan_page`). `hubs` lists the top
`N` articles by inbound degree (default `5`, override with `--top N`). `components` treats
links as undirected and reports the number of connected groups and the largest group's size —
useful for spotting a fragmented knowledge base.

### Exit-code contract for `graph --json`

| Code | Meaning                                                                        | JSON payload                                                    |
| ---- | ------------------------------------------------------------------------------ | --------------------------------------------------------------- |
| `0`  | Report produced (graph is read-only; always succeeds once the repo/KB resolve) | `{repo, articles, by_subdir, links, orphans, hubs, components}` |
| `1`  | Not in a git repository, or no KB directory                                    | `{"error": "..."}`                                              |

## CI Examples

### Fail on any lint error in GitHub Actions

```yaml
- name: Lint knowledge base
  run: |
    claude-wiki lint --json > lint.json
  shell: bash

- name: Report issues
  if: failure()
  run: jq '.issues[] | "\(.severity): \(.file) — \(.message)"' lint.json
  shell: bash
```

### Query and check for a cited answer

```bash
#!/usr/bin/env bash
answer=$(claude-wiki query "What is the migration policy?" --json | jq -r '.answer')
count=$(claude-wiki query "What is the migration policy?" --json | jq '.citations | length')

if [[ "$count" -eq 0 ]]; then
  echo "No sources found"
  exit 1
fi

echo "$answer"
```

### Structural-only lint for fast, API-free CI

```bash
claude-wiki lint --json --structural-only
```

This skips the LLM-based contradiction check, so the gate runs quickly and
without API cost.

### Gate CI on repository health

`status --json` exits non-zero when any check errors, so it works directly as
a CI gate. To also report which checks failed:

```bash
#!/usr/bin/env bash
claude-wiki status --json > status.json
rc=$?
if [[ "$rc" -ne 0 ]]; then
  jq -r '.checks[] | select(.status == "error") | "\(.name): \(.message)"' status.json
  exit "$rc"
fi
```

### Track knowledge-base growth and fragmentation

```bash
claude-wiki graph --json | jq '{articles, links, components: .components.count, orphans: (.orphans | length)}'
```

A rising `orphans` count or a growing `components` count signals a knowledge
base that is drifting apart — surface it in a dashboard or PR comment.
