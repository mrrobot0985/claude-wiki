# Quick Start

Get a knowledge base running in your repository in under five minutes.

______________________________________________________________________

## Prerequisites

- Python 3.12+
- `uv` installed (see [https://docs.astral.sh/uv/](https://docs.astral.sh/uv/))
- A git repository

______________________________________________________________________

## Step 1: Install

Install `claude-wiki` into your environment:

```bash
uv pip install claude-wiki
```

Or run directly with `uvx` (no install required):

```bash
uvx claude-wiki init
```

______________________________________________________________________

## Step 2: Choose a Mode

`claude-wiki init` defaults to **project mode**. Decide which mode fits your
workflow:

| Mode    | KB Location                                        | Best For                                       |
| ------- | -------------------------------------------------- | ---------------------------------------------- |
| project | `.claude/knowledge/` inside the repo               | Keeping code and docs together; per-repo vault |
| user    | `~/.local/share/claude-wiki-vault/<owner>/<repo>/` | Centralised vault; global graph view           |

You can switch later with `claude-wiki migrate`.

______________________________________________________________________

## Step 3: Initialise Your Repository

```bash
cd my-project
claude-wiki init
```

If your terminal is a TTY, `init` runs interactively and asks for mode and
timezone. Otherwise it uses safe defaults.

What gets created:

```text
my-project/
├── .claude-wiki.lock          # per-repo config (machine-managed, do not edit)
├── .claude/
│   ├── settings.local.json   # repo-local Claude Code hook registration
│   └── daily/                # conversation logs (created on first flush)
```

Use `--global` to write hooks to `~/.claude/settings.json` instead (affects all
sessions):

```bash
claude-wiki init --global
```

______________________________________________________________________

## Step 4: Capture Conversations

Once hooks are registered, Claude Code automatically flushes conversation
context to `daily/YYYY-MM-DD.md` at session end.

If you want to try compiling without waiting for a real session, copy the
synthetic daily log from the examples directory:

```bash
cp examples/minimal-walkthrough/daily/2026-06-20.md daily/2026-06-20.md
```

______________________________________________________________________

## Step 5: Compile

Process daily logs into structured articles:

```bash
claude-wiki compile
```

Sample output:

```text
Compiling daily/2026-06-20.md...
Created concepts/uv-python-toolchain.md
Created concepts/project-mode-venv.md
Created connections/uv-and-ci-pipelines.md
Updated minimal.md catalog
Cost: $0.32
```

Your knowledge base now contains:

```text
knowledge/
├── minimal.md                  # master catalog
├── log.md                      # build log
├── concepts/                   # atomic knowledge articles
└── connections/                # cross-cutting insights
```

______________________________________________________________________

## Step 6: Query

Ask questions against the compiled index:

```bash
claude-wiki query "how does uv project mode work?"
```

Sample output:

```text
uv project mode automatically creates or reuses a `.venv` directory when
`pyproject.toml` is present.

Sources:
- [[concepts/uv-python-toolchain]]
- [[concepts/project-mode-venv]]
```

______________________________________________________________________

## Step 7: Lint

Run health checks (no API cost):

```bash
claude-wiki lint --structural-only
```

Sample report saved to `.claude/reports/lint-YYYY-MM-DD.md`:

```text
Results: 0 errors, 0 warnings, 0 suggestions
All checks passed. Knowledge base is healthy.
```

______________________________________________________________________

## Step 8: Open in Obsidian

Point Obsidian at your vault root to browse the graph.

**Project mode vault:**

```text
my-project/.claude/knowledge/
```

**User mode vault:**

```text
~/.local/share/claude-wiki-vault/
```

In Obsidian, enable the graph view to see relationships between concepts.
Because `claude-wiki` uses `[[wikilinks]]` instead of markdown links, every
cross-reference becomes an edge in the graph.

______________________________________________________________________

## Cross-Repository Awareness

If you initialise multiple repos,
`~/.local/share/claude-wiki-vault/core.md` links them all with wikilinks.
The `SessionStart` hook injects a compact summary of other knowledge bases
alongside the current repo's catalog.

______________________________________________________________________

## Moving Data Safely

If you later change `kb_dir` or `daily_dir` in `.claude-wiki.lock`, migrate the
data:

```bash
claude-wiki migrate --dry-run
claude-wiki migrate
```

______________________________________________________________________

## Next Steps

- [Configure advanced options](../how-to/configure-repo.md)
- [Customise hooks](../how-to/customize-hooks.md)
- [CLI reference](../reference/cli.md)
- [Examples](../../examples/) — self-contained walkthrough without hooks
