# claude-wiki

[![PyPI version](https://img.shields.io/pypi/v/claude-wiki)](https://pypi.org/project/claude-wiki/)
[![CI](https://img.shields.io/github/actions/workflow/status/mrrobot0985/claude-wiki/ci.yml?label=CI)](https://github.com/mrrobot0985/claude-wiki/actions/workflows/ci.yml)
[![Python versions](https://img.shields.io/pypi/pyversions/claude-wiki)](https://pypi.org/project/claude-wiki/)
[![License](https://img.shields.io/pypi/l/claude-wiki)](https://github.com/mrrobot0985/claude-wiki/blob/main/LICENSE)

Installable Python package providing Claude Code hooks and a CLI for a personal
knowledge base. It captures context from your AI coding sessions automatically,
compiles it into a wiki of atomic, cross-linked articles, and feeds the relevant
index back into your next session — so knowledge compounds instead of evaporating.

Adapted from Karpathy's LLM Knowledge Base architecture.

## Features

- **Automatic capture.** Session hooks extract the meaningful turns of each
  Claude Code session into immutable daily logs — no manual note-taking.
- **Compile to atomic articles.** Daily logs are distilled by an LLM into one
  article per concept, plus cross-cutting `connections/` and filed `qa/`
  answers, each with YAML frontmatter and provenance backlinks. `--max-logs`
  caps the cost of a run.
- **Index-guided query (no RAG).** `query` reads the catalog first, then
  answers from the KB — retrieval grounded in structure rather than embeddings.
- **Health checks.** `lint` runs structural checks (broken wikilinks, orphan
  pages, sparse articles, frontmatter schema, and catalog↔article completeness)
  and optional LLM contradiction checks, with `--fix` for safe auto-repairs and
  machine-readable `--json` output and a stable exit-code contract for CI.
- **Topology & health monitoring.** `graph` reports the link topology —
  orphans, hubs, and connected components — so you can spot a fragmented KB at a
  glance; `status` diagnoses repository health with `--json` for CI gating.
- **Obsidian-friendly output.** Wikilinks, frontmatter, and a per-repo
  `{repo_name}.md` catalog keep the vault clean for Graph view; a global
  `core.md` registry links every registered repo with `[[owner/repo]]` links.
- **Project or user mode.** Keep the KB inside the repo (`.claude/knowledge/`)
  or in an XDG user-wide vault; `migrate` moves data between modes with rollback.
- **Fast, non-fatal hooks.** Handlers do only local I/O within the Claude Code
  timeout and offload LLM work to a backgrounded flush process; failures are
  logged, never fatal.

## How it works

```text
Claude Code session event
  -> claude-wiki-hook <Event>      (SessionStart / SessionEnd / PreCompact)
  -> hook handler (fast local I/O) -> backgrounded flush -> daily/YYYY-MM-DD.md

claude-wiki compile
  -> daily logs -> LLM -> kb_root/concepts/ · connections/ · qa/ + catalog

SessionStart hook -> injects catalog + recent daily log into next session
```

Daily logs are the append-only source of truth; the compiled wiki is LLM-owned
and rebuilt from them. The catalog is the primary retrieval mechanism — the
SessionStart hook injects it into each new session so context carries forward.

## Install

With `uv` (recommended):

```bash
uvx claude-wiki init
```

From source in a clone of this repo:

```bash
uv sync --frozen
```

Requires Python 3.12+. No API key — LLM calls use Claude Code's own credentials.

## Usage

Initialize a repository:

```bash
claude-wiki init
```

Daily commands:

```bash
claude-wiki compile [--all] [--file FILE] [--dry-run] [--continue-on-error] [--max-logs N] [--path PATH]
claude-wiki query "your question" [--file-back] [--json] [--path PATH]
claude-wiki lint [--structural-only] [--fail-on-warning] [--fix] [--threshold N] [--json] [--path PATH]
claude-wiki graph [--json] [--top N] [--path PATH]
claude-wiki status [--json] [--path PATH]
claude-wiki tags [--json] [--path PATH]
claude-wiki migrate [--dry-run] [--path PATH] [--kb-dir KB_DIR] [--daily-dir DAILY_DIR]
claude-wiki rename-catalog [--dry-run] [--path PATH]
```

`query`, `lint`, `status`, and `graph` accept `--json` for machine-readable
output and follow a stable exit-code contract. See the
[CLI reference](docs/reference/cli.md) for every flag.

Hook entry points (called by Claude Code via `.claude/settings.local.json` by
default):

```bash
claude-wiki-hook SessionStart
claude-wiki-hook SessionEnd
claude-wiki-hook PreCompact
```

## What `claude-wiki init` creates

```text
my-project/
├── .claude-wiki.lock              # per-repo config (machine-managed)
├── .claude/settings.local.json   # repo-local hook registration (default)
└── .claude/daily/                 # conversation logs (created on first flush)
```

Use `claude-wiki init --global` to write hooks to `~/.claude/settings.json`
instead. Use `claude-wiki init --path PATH` to target a different repository
root, or `--no-hooks` to skip hook installation.

## Configuration

`.claude-wiki.lock` fields:

```json
{
  "repo_name": "my-project",
  "repo_owner": "local",
  "layout_version": "2",
  "kb_dir": "project",
  "daily_dir": ".claude/daily",
  "reports_dir": "reports",
  "timezone": "UTC",
  "compile_after_hour": 18
}
```

- `layout_version` tracks the internal directory-layout generation. New
  repositories use `"2"`.
- `kb_dir` is `project` (repo-relative `.claude/knowledge/`), `user` (XDG
  vault `~/.local/share/claude-wiki-vault/<owner>/<repo>/`), or a custom path.
- `daily_dir` defaults to `.claude/daily` in project mode and
  `~/.local/share/claude-wiki-daily/<owner>/<repo>/` in user mode.
- `reports_dir` is **deprecated**; reports are written to the cache directory
  (`<repo>/.claude/reports/` in project mode).

Environment overrides: `CLAUDE_WIKI_PROJECT_DIR` (KB location),
`CLAUDE_WIKI_STATE_DIR` (machine state), `CLAUDE_WIKI_CACHE_DIR` (reports),
and `CLAUDE_WIKI_DEBUG` (verbose hook logging).

## Documentation

- Full docs in [`docs/`](docs/) — tutorials, how-to guides, reference, and
  explanation (Diátaxis).
- [`examples/`](examples/) for a self-contained walkthrough of compiled output.
- [`CHANGELOG.md`](CHANGELOG.md) for release history.
- [`docs/adr/`](docs/adr/) for architecture decisions.

## Community

- [Contributing](CONTRIBUTING.md) — branch naming, PR checklist, dev setup.
- [Code of Conduct](CODE_OF_CONDUCT.md) — Contributor Covenant 2.1.
- [Security policy](SECURITY.md) — responsible disclosure.

## Development

```bash
make dev              # install with dev dependencies
make install-precommit # install git hooks (run once per clone)
make test             # run pytest
make lint             # ruff check
make format           # ruff format + mdformat
make typecheck        # mypy
make precommit        # all pre-commit hooks
make all              # full CI gate (format, lint, typecheck, test, precommit)
```
