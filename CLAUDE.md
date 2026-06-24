# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

`claude-wiki` is an installable Python package (published to PyPI) providing Claude Code hooks and a CLI for a personal knowledge base. Hooks capture conversation context on session events; the CLI compiles daily logs into a wiki of atomic articles, queries them, and lints them. Adapted from Karpathy's LLM Knowledge Base architecture.

Two console entry points (see `pyproject.toml [project.scripts]`):

- `claude-wiki` → `claude_wiki.cli:main` — user-facing CLI
- `claude-wiki-hook` → `claude_wiki.hooks:main` — fast hook dispatcher invoked by Claude Code

## Commands

```bash
make dev              # uv pip install -e ".[dev]"
make install-precommit # one-time per clone: pre-commit install + commit-msg hook
make all              # full CI gate locally: format, lint, typecheck, test, precommit
make format           # ruff format + mdformat (.claude/skills, docs/, README, CHANGELOG, src AGENTS.md)
make lint             # ruff check .
make typecheck        # mypy src/  (--strict)
make test             # uv run pytest tests/
make test-cov         # pytest --cov=src/claude_wiki
make build            # uv build
```

Run a single test: `uv run pytest tests/test_compile.py -v` or by node `uv run pytest tests/test_compile.py::test_name`.

Format markdown **only** with the plugins — plain `mdformat` destroys YAML frontmatter:

```bash
uvx --with mdformat-frontmatter --with mdformat-gfm mdformat <files>
```

CI gate (`.github/workflows/ci.yml` + `.pre-commit-config.yaml`, all SHA-pinned): ruff check + ruff format --check + mypy --strict + pytest + mdformat --check + conventional commit message. Never bypass with `--no-verify`.

## Architecture

The package wires concrete collaborators in `factories.py` (`DefaultConfigResolver.build()` returns the five collaborators: `ConfigManager`, `DefaultHookRegistrar`, `MigrationManager`, `GitRemoteOwnerResolver`).

### Data flow

```
Claude Code session event
  → claude-wiki-hook <Event>   (hooks.py dispatches by event name)
  → hook_handlers/<event>.py   (fast local I/O only)
  → spawns flush.py as background `python -m claude_wiki.flush`
  → extracts last N turns → daily/YYYY-MM-DD.md

claude-wiki compile
  → commands/compile.py reads daily logs → LLM (claude-agent-sdk) →
     kb_root/concepts/ · connections/ · qa/ + {repo_name}.md catalog + log.md

SessionStart hook → injects {repo_name}.md catalog + recent daily log into next session
```

Handlers do only fast local I/O and offload LLM work to a backgrounded `flush.py` process, so hooks stay within their timeout. A `CLAUDE_INVOKED_BY` env recursion guard prevents nested hook triggers.

### Explicit registries (two of them)

- **CLI subcommands**: `cli._register_commands()` loads modules from an explicit `_COMMAND_MODULES` list in `commands/__init__.py`; any module exporting `register(subparsers, handlers)` is loaded. `init` and `migrate` are hard-coded in `cli.py`; the rest (`compile`, `query`, `lint`, `graph`, `status`, `tags`, `register`, `registry`, `rename-catalog`) are registered explicitly. Add a command by dropping a module in `commands/` and adding it to `_COMMAND_MODULES`.
- **Hook handlers**: `hooks._load_handlers()` loads modules from an explicit `_HANDLER_MODULES` list in `hook_handlers/__init__.py`; each module exports `register(handlers: dict[event, handler])`. Add a handler by dropping a module in `hook_handlers/` and adding it to `_HANDLER_MODULES`.

### Configuration & path resolution

`.claude-wiki.lock` (gitignored, per-repo, machine-managed) is the single source of truth — hydrated into the frozen `ProjectConfig` dataclass (`models.py`). `ConfigManager` (`config.py`) walks up from cwd looking for `.git` or `.claude-wiki.lock`, reads/writes the lock atomically, and resolves three directory trees via `platformdirs`:

- **kb_dir** modes: `project` (repo-relative `.claude/knowledge/`), `user` (XDG `~/.local/share/claude-wiki-vault/<owner>/<repo>/`), or an absolute/relative path. `CLAUDE_WIKI_PROJECT_DIR` overrides.
- **machine state** (`get_machine_state_dir`): logs, hashes, compile state — XDG `~/.local/state/...` in user mode, `.claude/state/` in project mode. `CLAUDE_WIKI_STATE_DIR` overrides.
- **cache** (`get_cache_dir`): ephemeral reports — XDG `~/.cache/...` in user mode, `.claude/` in project mode. `CLAUDE_WIKI_CACHE_DIR` overrides.

ADR-005 drove this split: machine files must never land in the Obsidian vault (they pollute Graph view), and daily logs must stay out of `git add .`. `layout_version` in the lock is schema metadata only; v1 layouts are rejected with a clear error (use `claude-wiki migrate` on a 0.x release before upgrading to v1.0.0).

### Migration

`MigrationManager` (`migration.py`) compares current vs previous `ProjectConfig` and moves `kb_dir`/`daily_dir`/machine-state data when they change (`claude-wiki migrate`, with `--dry-run`). It also renames `index.md`→`{repo_name}.md` and rewrites wikilinks (including the catalog's own self-links) during directory moves (ADR-006).

### Global registry

`GlobalIndexManager` (`global_index.py`) keeps `~/.local/share/claude-wiki-vault/.registry.json` (machine-managed, `fcntl` advisory-locked, corrupt-registry auto-backup) plus a human-readable `core.md` linking every per-repo KB with Obsidian wikilinks (`[[owner/repo/repo-name|repo-name]]`). `init` and `migrate` register/re-register repos here.

### Catalog naming (ADR-006)

Per-repo catalog is `{repo_name}.md`, **not** `index.md`. `catalog_utils.resolve_catalog(kb_root, repo_name)` centralizes resolution with backward-compatible heuristics (single `*.md`, then `index.md`) when `repo_name` is unavailable. Use it; don't hard-code `index.md`.

## Conventions

- `from __future__ import annotations` at top of every module; absolute imports.
- `mypy --strict` — annotate all public APIs.
- Conventional commits (`feat:`, `fix:`, `docs:`, `refactor:`, `test:`, `chore:`, `ci:`, `perf:`); feature branches `feat/`, `fix/`, etc. Never push directly to `main`.
- LLM calls go through `claude-agent-sdk` using Claude Code's own credentials — no API key in code or env.

### Commit signing & PR merges (STRICT)

- **Every commit and tag must be GPG-signed.** The repo's branch protection requires signed commits, and `release.yml` rejects any tag GitHub does not verify (aborting the release before publish). Use plain `git commit`/`git tag` — the global git config is already set up to sign and produce verified commits. Never disable signing or override the signing/identity config with `-c` flags or `GIT_*` env vars (the global `00-no-git-config-override` rule governs this).
- **Merge PRs with `gh pr merge --squash --delete-branch --admin --subject "<conventional title>" --body-file <clean body>`.** This repo's branch protection enforces `required_linear_history` (blocks `--merge`) AND `required_signatures` (blocks `--rebase`, because GitHub cannot re-sign rebased commits), so **`--squash` is the only allowed merge method**. GitHub signs the squash commit, so it is `verified` on `main`. The `--body-file` clean body is what keeps the squash commit free of a `Co-authored-by` trailer — never put one in the body.
- `release.yml` enforces this: its `verify-main` job rejects any tag whose signature GitHub does not verify, aborting the release before build/publish.

## Docs & decisions

- `docs/` is a Diátaxis-style site (tutorials / how-to / reference / explanation) with `docs/index.md` as the hub.
- `docs/adr/` holds numbered Architecture Decision Records (ADR-005 directory redesign, ADR-006 vault naming + Obsidian graph hygiene). New cross-cutting decisions get a new ADR; in-flight work is tracked in `docs/plan.md`.
- `src/claude_wiki/AGENTS.md` is the KB article schema reference (concept/connection/qa/frontmatter format, build log).
- `.claude/skills/` holds repo-local Claude Code skills: `claude-wiki-dev` (this package's dev reference, model-invocation disabled) plus per-command skills.

## Release

Tag-driven. Do **not** bump version in a PR. After a PR merges to `main`: edit `pyproject.toml` version, commit `chore: bump version to 0.x.y`, tag `v0.x.y`, push tag — `.github/workflows/release.yml` verifies the tag is on `main` **and that it is signed/verified**, builds, smoke-tests, publishes to PyPI via trusted publishing, and then creates a GitHub Release (with the wheel + sdist attached and the CHANGELOG section as notes) once PyPI publish succeeds. A local PyPI registry is available via `make pypi-start`/`pypi-stop`/`pypi-status`/`pypi-logs` for testing publishing.
