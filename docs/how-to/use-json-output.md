# Use JSON Output in CI and Scripts

Parse `claude-wiki` output reliably in automation.

______________________________________________________________________

## Commands That Support `--json`

| Command             | `--json` output                        |
| ------------------- | -------------------------------------- |
| `claude-wiki query` | Answered question + cited articles     |
| `claude-wiki lint`  | Structured list of issues              |
| `claude-wiki tags`  | Tag inventory with counts and examples |

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
