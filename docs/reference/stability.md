# Stability Policy

Effective from v1.0.0. Earlier 0.x releases do not carry stability guarantees — 0.x is pre-stable and may change between minor versions.

Starting with v1.0.0, claude-wiki follows [Semantic Versioning](https://semver.org/):

- **Patch releases** fix bugs without changing stable behavior.
- **Minor releases** add backward-compatible functionality to stable surfaces.
- **Major releases** may introduce breaking changes to stable surfaces only after a deprecation cycle where feasible.

## Stable surfaces

The following interfaces are considered stable from v1.0.0 onward. Breaking them requires a major version bump and, where possible, a prior deprecation cycle.

### CLI subcommands and flags

Top-level subcommands:

- `init`
- `migrate`
- `compile`
- `lint`
- `query`
- `register`
- `registry`
- `rename-catalog`
- `status`
- `tags`

Global flag:

- `--version`

Per-subcommand flags:

- `init`: `--path`, `--force`, `--global`, `--no-hooks`, `--kb-dir`, `--daily-dir`
- `migrate`: `--path`, `--dry-run`, `--kb-dir`, `--daily-dir`, `--reports-dir` (deprecated and ignored)
- `compile`: `--all`, `--file`, `--dry-run`, `--continue-on-error`, `--max-logs`, `--path`
- `lint`: `--structural-only`, `--fail-on-warning`, `--path`, `--json`, `--threshold`, `--fix`, `--dry-run`
- `query`: `--file-back`, `--path`, `--json`, `--category`, `--tag`, `--since`, `--max-chars`
- `register`: `--path`
- `registry`: `list`, `show`, `remove`, `clean`; `remove` accepts `--yes`
- `rename-catalog`: `--dry-run`, `--path`
- `status`: `--path`
- `tags`: `--path`, `--json`

### Hook dispatch contract

`claude-wiki-hook` is invoked by Claude Code as:

```text
claude-wiki-hook <Event>
```

Supported events:

- `SessionStart`
- `SessionEnd`
- `PreCompact`

Handlers are auto-discovered from `claude_wiki.hook_handlers`. The dispatcher reads hook-specific JSON from stdin and returns a JSON object on stdout. A `CLAUDE_INVOKED_BY` recursion guard prevents nested hook triggers from re-entering the flush pipeline.

### `.claude-wiki.lock` schema

The lock file is a JSON object matching `ProjectConfig` in `claude_wiki.models`. Current `layout_version` is `"2"`.

| Field                | Type           | Default        | Description                             |
| -------------------- | -------------- | -------------- | --------------------------------------- |
| `repo_name`          | string         | directory name | Repository identifier                   |
| `repo_owner`         | string         | `"local"`      | Namespace for XDG path resolution       |
| `layout_version`     | string         | `"2"`          | Schema version; currently `"2"`         |
| `kb_dir`             | string or path | `"project"`    | KB location mode or custom path         |
| `daily_dir`          | string or path | mode-aware     | Source daily-log directory              |
| `reports_dir`        | string or path | `"reports"`    | Deprecated and ignored                  |
| `timezone`           | string         | `"UTC"`        | IANA timezone for timestamps            |
| `compile_after_hour` | integer        | `18`           | Earliest hour for automatic compilation |

All path fields expand `~` to the user's home directory. `timezone` is validated against the IANA Time Zone Database at load time.

### KB article frontmatter schema

The compiler and linter expect YAML frontmatter on articles under `concepts/`, `connections/`, and `qa/`.

**Concept articles** (`concepts/*.md`):

- Required: `title`, `sources`
- Recommended: `aliases`, `tags`, `created`, `updated`

**Connection and Q&A articles** (`connections/*.md`, `qa/*.md`):

- Required: `title`, `sources`
- Recommended: `created`, `updated`

Q&A articles produced by `query --file-back` additionally include `question`, `consulted`, and `filed` fields. The catalog (`{repo_name}.md`) and build log (`log.md`) do not require frontmatter. Daily logs are cited as plain text, never as `[[daily/...]]` wikilinks.

### Config environment-variable overrides

These environment variables override the corresponding `.claude-wiki.lock` resolution:

- `CLAUDE_WIKI_PROJECT_DIR` — overrides `kb_dir`
- `CLAUDE_WIKI_DAILY_DIR` — overrides the default `daily_dir`
- `CLAUDE_WIKI_STATE_DIR` — overrides the machine-state directory
- `CLAUDE_WIKI_CACHE_DIR` — overrides the cache directory

`CLAUDE_WIKI_DEBUG` is a diagnostic toggle that lowers the log level to DEBUG; it does not change configuration values.

### Directory-layout contract

claude-wiki keeps three buckets separate per ADR-005:

1. **Vault / data** — human-readable KB articles.
1. **Machine state** — compilation hashes, costs, and flush logs.
1. **Cache** — ephemeral reports and temporary context files.

`kb_dir` modes resolve as follows:

- `"project"` — repo-relative `.claude/knowledge/`
- `"user"` — `~/.local/share/claude-wiki-vault/<owner>/<repo>/`
- custom relative path — anchored under the repo root
- custom absolute path — used as-is

`daily_dir` defaults are mode-aware:

- `"project"` mode — `.claude/daily/`
- `"user"` mode — `~/.local/share/claude-wiki-daily/<owner>/<repo>/`

Machine-state and cache directories follow the same mode:

- Project mode: `.claude/state/` and `.claude/reports/`
- User mode: `~/.local/state/claude-wiki/repos/<owner>/<repo>/` and `~/.cache/claude-wiki/repos/<owner>/<repo>/`

## Experimental surfaces

The following features work but are not yet covered by the long-term stability guarantee. They may change between minor versions while we learn how they are used.

- `lint --fix` and `lint --dry-run` — apply safe structural repairs in place. The set of fixable issues and the exact repair behavior may evolve.
- `compile --continue-on-error` — keep compiling remaining daily logs after a single-log failure. The failure-reporting format and interaction with incremental state may be refined.
- LLM-driven checks — running `lint` without `--structural-only` asks an LLM to detect contradictions. Output format, cost, and heuristics are subject to change.

If you build scripts or CI around experimental surfaces, pin them defensively and review the release notes before upgrading.

## Deprecation policy

A stable surface is retired in three steps:

1. The old behavior is marked deprecated in the release notes and, where practical, emits a runtime warning for at least one minor version.
1. The next major version may remove or replace the deprecated behavior.
1. If a deprecation warning cannot be emitted automatically, the release notes document the replacement and the minimum version that supports it.

Security fixes and data-integrity fixes may be backported to the current major release line without following the full deprecation cycle.

## Decision log

Architecture decisions that shape these guarantees are recorded in the ADRs:

- [ADR-005: Knowledge Base Directory Redesign](../adr/005-kb-directory-redesign.md)
- [ADR-006: Vault Naming and Obsidian Graph Hygiene](../adr/006-vault-naming-and-obsidian-graph-hygiene.md)

See the full list under [Architecture Decision Records](../index.md#architecture-decision-records) in the documentation hub.
