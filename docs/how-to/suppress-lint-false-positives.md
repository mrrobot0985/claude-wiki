# Suppress Lint False Positives

Mute lint issues you have reviewed and decided to accept.

______________________________________________________________________

## Create an Ignore File

Add a file named `.claude-wiki-lint-ignore` at the repository root. Each non-empty,
non-comment line is a rule in this format:

```text
path::check::reason
```

- **path** — article path relative to the KB root, for example
  `concepts/legacy.md`. Supports `fnmatch` globs such as `concepts/*.md`.
- **check** — the exact check name from the lint report, for example
  `orphan_page` or `tag_single_use`.
- **reason** — a short human-readable explanation. It is not used by the tool,
  but it makes the decision auditable.

Lines starting with `#` and blank lines are skipped.

## Example File

```text
# Intentional one-off tag for draft articles
qa/drafts.md::tag_single_use::intentional draft marker

# Legacy concept articles imported without aliases
concepts/legacy-*.md::frontmatter_missing_aliases::pre-schema import

# Reference article that should not be linked from other pages
concepts/cli-flags.md::orphan_page::standalone reference kept by design
```

## How Matching Works

An issue is ignored when **both** of these are true:

1. Its `check` name equals the rule's `check`.
1. Its `file` path matches the rule's `path` glob.

So a rule `concepts/*.md::orphan_page::legacy` only suppresses orphan-page
warnings inside `concepts/`. It does not suppress the same check in
`connections/` or `qa/`, and it does not suppress broken-link errors.

## Verify the Ignore Rules

Run lint and confirm the suppressed issues no longer appear and the exit code
has dropped:

```bash
claude-wiki lint
claude-wiki lint --json
```

Ignored issues are removed from both the human-readable summary and the JSON
payload, and they are not counted toward the exit status.

## Keep the File Honest

Add a rule only after you have reviewed the issue. Empty or vague reasons such
as `noise` make it harder to spot real regressions later. Treat the file as a
living TODO list: remove a rule once the underlying article is fixed.
