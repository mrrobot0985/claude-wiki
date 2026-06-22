# Implementation Plan — Road to v1.0

> **Status: active.** Tracks the push to the v1.0 stable release. The completed
> ADR-006 execution plan that previously lived here is preserved in
> [ADR-006](adr/006-vault-naming-and-obsidian-graph-hygiene.md) and in git
> history.

## Goal

Ship a **v1.0.0 stable** release: a frozen, documented surface (CLI, hooks,
lock-file schema, article frontmatter) backed by a reliable, signed release
pipeline, with cross-platform packaging and a stability/semver policy — and a
**ruthless hardening + simplification pass** that fixes the concrete failures
flagged in the v0.13.\* external review (compile write surface, compile cost,
config/migration surprises, concurrency races, dead abstraction) without adding
new scope.

## v1.0 hardening & simplification plan (ADRs 008–016)

Ratified 2026-06-22 by both external reviewers (Brutal: "Ship it"; Honest: "A-").
ADRs 008–015 are **Accepted**; ADR-016 is **Rejected** (kept on record). The full
ADR bodies live in this section as the single source of truth until each is
promoted to its own file under `docs/adr/` when the docs commit is authorized.

### Execution discipline

- Execute the 5 phases as written. **Add nothing else.** No new features, no
  new abstractions, no speculative seams.
- After Phase 1: **regression pass** on hooks + `compile --all` + Obsidian graph
  view before starting Phase 2+ (Honest).
- After v1.0.0: **architecture freeze.** No redesign churn for a while.

### Reconciliation notes (ground-truth verification against current code)

- `object.__setattr__` in `ProjectConfig.__post_init__` is NOT a smell —
  idiomatic + tested (`tests/test_models.py:180-197`).
- Path resolution is already centralized in `ConfigManager`
  (`config.py:230-300`); ADR-010 is scoped to deduping 2–3 helpers +
  lazy-migration removal, not a `PathResolver` rewrite.
- `.claude-wiki.lock` holds only config (runtime state is in the registry) —
  the "config/state mix" criticism is false.
- ADR-002 cross-filesystem rollback check is documented but UNIMPLEMENTED
  (`migration.py`) — concrete risk, addressed in ADR-010.
- Daily-log append race (`flush.py:214-238`) — unguarded RMW, in ADR-013.

### Already fixed — do NOT re-litigate

Hook input validation, timezone crash tests, wheel-install smoke test
(CI smoke job + `tests/test_packaging.py`), `.lock` config/state separation,
drift-guard tests (healthy insurance).

### Roadmap (5 phases, security-first)

#### Phase 1 — Security & compile safety

| #   | Item                                                                                                 | Failure solved                                                                   | Files                                  | Status    |
| --- | ---------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- | -------------------------------------- | --------- |
| 1.1 | Sandbox compile writes: drop `acceptEdits`, constrained response schema, Python-side path validation | LLM writes anywhere under `repo_root`; no traversal guard (`compile.py:261-269`) | `commands/compile.py`, new `writer.py` | clear-cut |
| 1.2 | Path-traversal + category guard on generated filenames                                               | `../`/absolute paths could escape `kb_root`                                      | `writer.py`, tests                     | clear-cut |
| 1.3 | Compile cost control: context cap, per-log USD cap (reuse `total_cost_usd`), opt-in `--model`        | $7.79/2 logs; no budget (`compile.py:186-279`)                                   | `commands/compile.py`, `models.py`     | clear-cut |
| 1.4 | Schema-validate LLM output (frozen dataclasses) before writing                                       | LLM-written files unchecked                                                      | `writer.py`, `catalog_utils.py`        | clear-cut |

**Phase 1 exit gate:** full regression pass on hooks + `compile --all` + Obsidian
graph view before starting Phase 2 (Honest).

#### Phase 2 — Concurrency hardening

| #   | Item                                                              | Failure solved                            | Files                 | Status    |
| --- | ----------------------------------------------------------------- | ----------------------------------------- | --------------------- | --------- |
| 2.1 | Lock daily-log append (`daily.log.lock`, per-repo)                | RMW race (`flush.py:214-238`)             | `flush.py`            | clear-cut |
| 2.2 | Lock `state.json` RMW (`state.json.lock`)                         | RMW race (`compile.py:373-438`)           | `commands/compile.py` | clear-cut |
| 2.3 | Per-repo compile serialization (covered by the `state.json` lock) | two concurrent compiles interleave        | `commands/compile.py` | clear-cut |
| 2.4 | Keep existing registry `fcntl` lock                               | already correct (`global_index.py:60-84`) | ---                   | clear-cut |

#### Phase 3 — Config/path consolidation

| #   | Item                                                                                                    | Failure solved                                                              | Files                                       | Status    |
| --- | ------------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ------------------------------------------- | --------- |
| 3.1 | Dedupe path helpers into `ConfigManager`                                                                | `global_index._resolve_path`, `status._check_daily` duplicate logic         | `global_index.py`, `status.py`, `config.py` | clear-cut |
| 3.2 | Dedupe `ProjectConfig` validation (keep dataclasses)                                                    | validation duplicated in `__post_init__` + `from_dict` (`models.py:25-111`) | `models.py`, `config.py`                    | clear-cut |
| 3.3 | Remove lazy migration from `load()`; refuse-with-actionable-error on legacy; `migrate` is the only path | side-effecting config reads (`config.py:103-214`)                           | `config.py`, `cli.py`, `migration.py`       | clear-cut |
| 3.4 | Implement ADR-002 cross-filesystem pre-flight + warning inside `migrate`                                | documented but missing (`migration.py`)                                     | `migration.py`                              | clear-cut |

#### Phase 4 — Abstraction removal

| #   | Item                                                                             | Failure solved                                                                                       | Files                                   | Status    |
| --- | -------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- | --------------------------------------- | --------- |
| 4.1 | Explicit command registry; kill `pkgutil` discovery                              | import errors silently swallowed (`cli.py:168-176`)                                                  | `cli.py`, `commands/__init__.py`        | clear-cut |
| 4.2 | Explicit hook registry                                                           | same pattern (`hooks.py:52-60`)                                                                      | `hooks.py`, `hook_handlers/__init__.py` | clear-cut |
| 4.3 | Drop unused Protocols/factories                                                  | single-implementation seams (`interfaces.py`, `factories.py`)                                        | `interfaces.py`, `factories.py`, tests  | clear-cut |
| 4.4 | Remove dead code                                                                 | `_format_link` (`global_index.py:270-276`), `resolve_catalog` None branch (`catalog_utils.py:91-97`) | `global_index.py`, `catalog_utils.py`   | clear-cut |
| 4.5 | Keep `argparse`; fix `_completions.py` private-API brittleness only if it recurs | private `argparse` internals (`_completions.py:35`)                                                  | `_completions.py`                       | clear-cut |

#### Phase 5 — Layout freeze & v1.0 release

| #   | Item                                                | Failure solved              | Files                            | Status                  |
| --- | --------------------------------------------------- | --------------------------- | -------------------------------- | ----------------------- |
| 5.1 | ADR-014: freeze layout v2                           | users fear another redesign | `docs/adr/014`                   | clear-cut               |
| 5.2 | Remove legacy v1 migration code (post grace period) | dead weight after freeze    | `config.py`, `migration.py`      | clear-cut               |
| 5.3 | v1.0.0 tag + CHANGELOG                              | no stable baseline          | `pyproject.toml`, `CHANGELOG.md` | **needs user sign-off** |

### ADR-008: Keep Hand-Rolled Dataclasses; Deduplicate Validation

**Status:** Accepted

**Context:** `ProjectConfig` is a frozen dataclass (`models.py:25-26`). Validation
is written twice: in `__post_init__` (`models.py:38-67`) and in `from_dict`
(`models.py:70-101`). The `object.__setattr__` in `__post_init__` is the standard
idiom for derived fields on a frozen dataclass and is tested. `pydantic` is on
disk only transitively (`claude-agent-sdk` → `mcp` → `pydantic`); adopting it would
add a declared dependency and a model-layer migration for a struct with \<12
fields.

**Decision:** Keep frozen dataclasses. Reject Pydantic for v1. Consolidate
validation into one factory path (`from_dict`); `__post_init__` keeps only
invariants not expressible in the factory (timezone `ZoneInfo` check, `~`
expansion). Retain `object.__setattr__` for derived path fields.

**Implementation guardrails (Honest):** the factory path must exercise the **same
checks** as `__post_init__` (timezone, path expansion, `compile_after_hour`
range) to avoid divergence — exactly one validation path, not two
partially-overlapping ones.

**Consequences:** No new declared dependency; single validation dialect; preserved
`expanduser` semantics. Remaining cost: hand-rolled validation, but the
duplicated tax is removed.

**Alternatives rejected:** Adopt Pydantic v2 — "adds zero value here" (Brutal);
model-dumping quirks + serialization edge cases for a flat config struct.

### ADR-009: Replace `pkgutil` Auto-Discovery with Explicit Registries

**Status:** Accepted

**Context:** `cli.py:168-176` and `hooks.py:52-60` use `pkgutil.iter_modules` +
dynamic import and swallow any `Exception`, silently hiding broken modules. The
command/hook set is static; the extensibility seam is unused.

**Decision:** Replace with explicit registries in `commands/__init__.py` and
`hook_handlers/__init__.py`, imported directly so import failures propagate
loudly. Brutal: "do this early — this is the soul of v1."

**Consequences:** Fail-fast in CI; single source of truth for the command surface;
adding a command/hook requires editing the registry.

**Alternatives rejected:** Keep `pkgutil` with narrower exception handling (still
hides real failures); entry-points plug-in mechanism (more indirection, zero
external consumers).

### ADR-010: Consolidate Path Helpers; Remove Lazy Migration from `load()`

**Status:** Accepted

**Context:** `ConfigManager.load()` performs lazy layout migration as a side
effect of every config read (`config.py:103-214`, `_maybe_migrate_legacy`), with
LIFO rollback on partial failure. ADR-002 admits the cross-filesystem `st_dev`
pre-flight is documented but **not implemented**, and rollback reverses every
move unconditionally. Path logic is duplicated in `global_index._resolve_path` and
`status._check_daily`.

**Decision:**

1. `load()` becomes pure read + validate — no side effects.
1. On legacy layout, `load()` refuses with a loud actionable error: `Legacy layout detected. Run \`claude-wiki migrate\` to update paths.\`
1. `claude-wiki migrate` is the only migration path; it must be idempotent and
   safe.
1. Implement ADR-002's cross-filesystem pre-flight **inside `migrate`**: compare
   `os.stat(src).st_dev` vs `os.stat(dst.parent).st_dev`; same FS → proceed;
   different FS → emit a prominent, actionable warning and skip automatic
   rollback for that move.
1. Consolidate `global_index._resolve_path` and `status._check_daily` into
   `ConfigManager` helpers. Do **not** create a separate `PathResolver` class.

**Implementation guardrails (Honest):** the cross-FS warning must be prominent and
actionable, e.g. `"Cross-filesystem move detected. Manual verification of moved files recommended after completion."` — not a debug-level log.

**Consequences:** Predictable, side-effect-free config loads; explicit one-time
user migration; safer cross-FS moves; one owner of path semantics. Tests relying
on implicit migration must call `migrate` explicitly.

**Alternatives rejected:** Keep lazy migration in `load()` (least-surprise
violation); separate `PathResolver` class (over-engineering — `ConfigManager`
already owns paths).

### ADR-011: Compile Cost Control

**Status:** Accepted

**Context:** Compile includes the full index + all existing articles per log,
`max_turns=30`, no budget (`compile.py:186-279`). A 2-log run cost $7.79.
Incremental-by-hash + `--max-logs` exist but neither bounds prompt size or spend.
**Grounding:** `ResultMessage.total_cost_usd` is already consumed at
`compile.py:275-276`; `state.json` already tracks per-log `cost_usd`
(`compile.py:430`) and running `total_cost` (`compile.py:433`) — so the cap reuses
existing infrastructure.

**Decision:**

1. Existing-articles context budget: hardcode 15,000–25,000 chars.
1. Eviction: drop oldest first by recency + degree (hub articles with many
   wikilinks stay longer). The catalog/index is always included and does not
   count toward the budget.
1. Per-log USD cap: hardcode $0.50–$1.00 using `total_cost_usd`; above the cap, fail
   fast, mark the log failed for retry/manual review, log truncated-budget usage.
   Pre-call guard: reject obviously oversized prompts via `len(prompt)/4` token
   estimate before spending.
1. Model selection: capable model default; `--model`/`--cheap` opt-in only with
   an explicit quality warning.
1. Defaults hardcoded in v1 (hidden `--context-budget` only if users demand).
1. Schema-validate every LLM response before writing (see ADR-012).
1. No semantic determinism — verify structure, not semantic identity.
1. Document `compile --all` for periodic re-consolidation.

**Implementation guardrails (Brutal):** make the eviction heuristic **dead
simple** — recency plus a cheap hub-weight (reuse the existing inbound-link count
from `graph_utils`, do not compute graph degree fresh in the hot path). Hubs
staying longer is fine; do not overthink graph degree. A sort key like
`key = (is_hub, mtime)` is enough.

**Consequences:** Bounded per-log cost; predictable bills; occasional weak distant
cross-links (recovered via index + periodic `compile --all`); cheaper model is an
explicit, warned opt-in.

**Alternatives rejected:** Unbounded full context (cost cliff); cheaper model as
default (quality matters for a personal KB); user-configurable budget in v1 (UI
complexity before need); semantic determinism (research problem, not a product
fix).

### ADR-012: Drop `acceptEdits` for a Constrained Write Schema

**Status:** Accepted

**Context:** `compile` invokes the agent SDK with
`allowed_tools=["Read","Write","Edit","Glob","Grep"]`,
`permission_mode="acceptEdits"`, `cwd=repo_root`, `max_turns=30`
(`compile.py:261-269`) — the LLM writes KB files directly with no `kb_root` sandbox
or path-traversal guard. `query --file-back` is safer: Read/Glob/Grep only,
`cwd=kb_root`, Python slugifies + writes (`query.py:235-238`, `399-458`) — but it
returns **prose** and writes **non-atomically**, so it is the *path-confinement*
template to generalize, not to copy verbatim.

**Decision:** Generalize and improve on the `query --file-back` pattern.

1. LLM tool set: `Read`, `Glob`, `Grep` only. Remove `Write`, `Edit`,
   `acceptEdits`. Set `cwd=str(kb_root)`.
1. Structured response: the LLM returns JSON describing articles to write — each
   with `title`, `slug`, `category`, `frontmatter`, `body` (full replacement
   content, not in-place edits).
1. Python-side validation before any write: slug filename-safe + non-empty (same
   regex as `_slugify`); `category` in `{concepts,connections,qa}`; target path
   exactly `kb_root/<category>/<slug>.md`, `kb_root/<repo_name>.md`, or
   `kb_root/log.md`; reject `..`, absolute paths, out-of-set categories.
1. Atomic writes from Python (temp + `os.replace`), constrained to `kb_root`,
   under the ADR-013 locks.
1. **Output schema validation:** parse the LLM's JSON into frozen `dataclass`
   models (e.g. `CompiledArticle`) that validate in `__post_init__` — mirror the
   `ProjectConfig` style. Do **not** introduce Pydantic or `jsonschema` (both
   transitive only via `mcp`; declaring either contradicts ADR-008 and Brutal's
   verdict).

**Implementation guardrails (both reviewers):**

- **Fail-fast JSON parsing (Brutal):** LLM JSON is never perfect. Parse
  defensively; on any malformed/missing/oversized entry, reject that article (or
  the whole response) with a clear error and mark the log failed — do not
  silently write partial garbage. Re-run is the recovery path.
- **Output-size fallback (Honest):** requiring full article bodies (including
  updated existing articles) in one structured response may hit the model's
  output-token limit on larger KBs. Have a fallback ready — chunk
  **category-by-category** (one LLM round per category) or request "summarize
  changes only" for updates. **Test this early with real daily logs.** Never
  reintroduce multi-turn `Edit` writes as the fallback.

**Consequences:** Materially smaller attack/corruption surface (no LLM filesystem
god-mode); path traversal eliminated mechanically; structured output is easier to
validate/retry than arbitrary edits. Tradeoff: more code in compile (writer +
validator); prompt must request full replacement articles.

**Alternatives rejected:** `acceptEdits` + `cwd=kb_root` (half-measure — still
allows `../evil.md` and `Edit` on catalog/log); `acceptEdits` + post-write audit
(detects corruption after the fact).

### ADR-013: Concurrency — Repo-Level Advisory Locks

**Status:** Accepted

**Context:** The global registry already uses a bounded `fcntl` advisory lock
(`global_index.py:60-84`: `.lock` suffix, `LOCK_EX|LOCK_NB`, bounded retries →
`TimeoutError`, `finally` release). Two unguarded RMW cycles: daily-log append
(`flush.py:214-238` — two concurrent SessionEnd/PreCompact flushes can both read
`existing`, both append, second `os.replace` drops the first's entry) and
`state.json` update (`compile.py:373-438`).

**Decision:** Add advisory `fcntl` locks only where concrete races exist, reusing
the `global_index.py:60-84` pattern:

1. **Daily-log append** — wrap `append_to_daily_log` (`flush.py:221-237`) with a
   per-repo lockfile `daily.log.lock` (in the machine-state dir).
1. **`state.json` RMW** — wrap the load-update-save sequence (`compile.py:373`→
   `438`) with `state_path.with_suffix(".json.lock")`.
1. **Per-repo compile serialization** — the `state.json` lock naturally serializes
   compiles for a given repo (every compile mutates `state.json`); different repos
   use different state files and stay parallel. No separate "compile lock."
1. Document: concurrent reads (query, status) are safe; concurrent writes
   serialize briefly. No queue, no lock-free, no SQLite, no lock server. `fcntl`
   is Unix-only; Windows gets a no-op stub (`sys.platform == "win32"` guard).

**Implementation guardrails (Honest):** document the **lack of write serialization
on Windows** explicitly in the README/status output — not just in code comments.
For a personal tool it's low risk, but be explicit.

**Consequences:** Prevents the two concrete clobbering races; brief write
serialization acceptable for a personal tool; no new dependencies (stdlib
`fcntl`); Windows not serialized (documented).

**Alternatives rejected:** SQLite registry/queue (DB + migration story for no
concrete failure); lock server (absurd for single-user); lock-free append-only
state (hypothetical scale problem).

### ADR-014: Freeze Layout v2

**Status:** Accepted

**Context:** ADR-005/006/007 settled the v2 layout (vault-at-root, daily logs
outside the vault, XDG state/cache). Implemented across v0.3.0–v0.5.x. v1.0 needs
a stable structural baseline.

**Decision:** Freeze v2 as the stable layout for v1.0. No new auto-migrations
post-v1. The only active migration code is the v1→v2 path from ADR-005. After a
grace period, legacy v1 migration code may be removed.

**Consequences:** Users can script/backup against stable paths; no ongoing
multi-layout support obligation; v1 migration code carried briefly post-v1.0.

**Alternatives rejected:** Continue redesigning post-v1 (strands users/tooling);
keep auto-migrating indefinitely (accumulates debt).

### ADR-015: Keep `argparse`; Reject Typer/Click for v1

**Status:** Accepted

**Context:** The CLI problems are not `argparse` but `pkgutil` discovery
(ADR-009) and the completion generator's private `argparse` internals
(`_completions.py:35`, `argparse._SubParsersAction`).

**Decision:** Keep `argparse` for v1. Reject Typer/Click. Isolate and guard the
private-API usage in `_completions.py`; covered by the existing drift-guard test.
Migration threshold (for the record): migrate only when (a) arg-handling drift
causes real bugs, (b) completion-generator pain recurs, or (c) rich
auto-documented option groups are needed.

**Implementation guardrails (Brutal):** if `_completions.py` private-API usage
hurts again post-v1, reconsider the generator (or migration) then — not now.
Correct call to keep argparse for v1.

**Consequences:** Zero dependency cost; no migration churn; private-API use
isolated and guarded.

**Alternatives rejected:** Typer (dependency + annotation boilerplate + churn);
Click (same cost, less ergonomics).

### ADR-016: Reject MCP Server for In-Session KB Commands

**Status:** Rejected (2026-06-22 — external review + anti-over-engineering rule)

**Context:** The draft proposed a third entry point `claude-wiki-mcp` (stdio)
exposing read-only commands (`query`, `lint --structural-only`, `graph`,
`status`, `tags`, `registry list/show`) as typed, lazy-loaded MCP tools, keeping
mutating/expensive commands CLI-only. Today the non-hooks commands are invoked
via CLI or Claude Code skills (markdown prompts, always-in-context once loaded).

**Decision:** Do **not** add an MCP server for v1.0. Keep the two-surface design:
hooks for capture, CLI for heavy/mutating/expensive ops, skills for read/query
guidance. `compile` and all mutating/expensive commands remain CLI/human-only
**permanently** — never model-invocable.

**Rationale:** The proposal's benefits (typed schemas, lazy loading, structured
returns, no subprocess-per-call) were real but did not clear the bar of a
*concrete current failure* — skills work today and no user has reported
skill-prose cost as a problem. A long-running server process + `mcp` SDK
dependency surface + `.mcp.json` config + three-surface sync burden is not
justified for a single-user personal tool. The read-only/mutating boundary is
already enforced by simply not exposing mutating commands as skills. Brutal:
"Skill prompts are already good enough… strip, don't add." Making `compile`
model-invocable risks infinite loops and surprise bills.

**Alternatives considered:**

- (a) Full MCP server — rejected (this ADR).
- (b) Read-only MCP boundary only — rejected (same maintenance surface for
  marginal gain).
- (c) Slim existing skill markdown prompts without a new process — **defer.**
  Skills are already concise (40–55 lines); no measured context-cost problem. If
  one appears, trim `claude-wiki/SKILL.md` duplicated flag tables only; do not
  expand into a project.

**Consequences:** Keep a simpler two-surface architecture; no new
process/dep/config. Forgo typed tool schemas and lazy loading for read-only ops.
Permanent boundary: `compile`/`init`/`migrate`/`rename-catalog`/`register`/
registry-cleanup never become skills or MCP tools.

**Closing note:** The proposal was not wrong on the merits — typed MCP tools are
a better abstract interface than prose skill prompts — but premature for a
single-user tool with no measured failure. Revisit only if KB-scale skill-prompt
context cost becomes a measured problem, or a remote/multi-user surface is
genuinely needed.

### Testing & verification requirements (Honest)

Folded into the relevant phases — not a separate phase, no new scope:

- **`writer.py` (ADR-012):** aggressive negative tests — path-traversal attempts
  (`../`, absolute paths, symlinks), bad slugs, out-of-set categories, oversized
  output, malformed/missing JSON fields. The failure path is the security
  guarantee; test it hard.
- **Migration (ADR-010):** tests must now explicitly invoke `migrate` (no implicit
  side-effect path). Cover the legacy-detect → refuse-with-actionable-error path
  and the cross-FS warning path.
- **Concurrency (ADR-013):** simulate concurrent flushes/compiles (threads +
  mocked FS, or `pytest` `tmp_path` with two threads) — assert no dropped
  daily-log entries and no clobbered `state.json`.
- **Validation factory (ADR-008):** tests assert the single factory exercises
  every check `__post_init__` used to (timezone, path expansion, hour range) — no
  divergence.
- **Phase 1 exit gate:** full regression pass on hooks + `compile --all` +
  Obsidian graph view before starting Phase 2.

### ADR status summary

| ADR | Title                                    | Status   |
| --- | ---------------------------------------- | -------- |
| 008 | Keep dataclasses; dedupe validation      | Accepted |
| 009 | Explicit command/hook registries         | Accepted |
| 010 | Consolidate paths; remove lazy migration | Accepted |
| 011 | Compile cost control                     | Accepted |
| 012 | Constrained write schema                 | Accepted |
| 013 | Advisory `fcntl` locks                   | Accepted |
| 014 | Freeze layout v2                         | Accepted |
| 015 | Keep argparse                            | Accepted |
| 016 | MCP server                               | Rejected |

Every roadmap item is **clear-cut** except **5.3 (v1.0.0 tag)** which needs user
sign-off.

## Done

### Features (shipped through v0.13.0)

- `compile --max-logs` cost guard (alias `--limit`, oldest-first, default
  unlimited) — v0.12.0
- `lint` catalog↔article completeness check (`uncatalogued_article`,
  `stale_catalog_entry`) + `lint --fix`/`--dry-run` safe auto-repairs — v0.11.0,
  v0.12.0
- `status --json` machine-readable health output — v0.13.0
- `claude-wiki graph` topology report (orphans, hubs, connected components) with
  a shared `graph_utils` module — v0.13.0
- `query` scope filters (`--category`, `--tag`, `--since`, `--max-chars`),
  `query --json`, `lint --json`, `tags` command + `--tag` filter — v0.9.0–v0.10.0
- Atomic `flush` writes (daily log + dedup state) — v0.12.0
- Shell completions (bash/zsh/fish, drift-guarded) + man page — v0.10.0

### Release pipeline (hardened)

- Tag-driven: signed tags (`git tag -s`, non-prefixed identity → GitHub-verified)
  trigger `release.yml`.
- `release.yml` `verify-main` rejects unverified tags before build/publish
  (signed-tag gate).
- `publish` to PyPI via trusted publishing (OIDC, checkout-free).
- `github_release` job creates a GitHub Release (wheel + sdist + CHANGELOG notes),
  checkout-free (notes extracted from the sdist) and idempotent (create-or-upload).
- Only `verify-main` and `build` check out the source (where actually needed).

### Docs & policy

- Stability & SemVer policy (`docs/reference/stability.md`) + 0.x→1.0 upgrade
  guide (`docs/how-to/upgrade-to-v1.md`).
- How-tos for JSON output, `graph`, tags, completions, lint-ignore, query scope,
  migration, hooks.
- README refreshed for the v0.12/v0.13 feature set.
- ADRs 005–007 (directory redesign, vault naming/graph hygiene, no wikilinks to
  daily logs).

### Merge/signing discipline

- All merges are `--squash` (the repo enforces `required_linear_history` +
  `required_signatures`, so `--merge`/`--rebase` are blocked). PR commits use the
  ID-prefixed author email (no co-author trailer); tags use the non-prefixed
  signed identity (verified). See `CLAUDE.md` → "Commit signing & PR merges".

## Remaining (gated on environment / user decision)

- **Cross-platform packaging** — open issues:

  - [#149](https://github.com/mrrobot0985/claude-wiki/issues/149) Homebrew
    formula (macOS)
  - [#150](https://github.com/mrrobot0985/claude-wiki/issues/150) AUR package
    (Arch Linux)
  - [#151](https://github.com/mrrobot0985/claude-wiki/issues/151) Scoop manifest
    (Windows)

  Each needs its target OS to verify the install end-to-end
  (`brew install` / `makepkg -si` / `scoop install`); not verifiable from a Linux
  sandbox.

- **v1.0.0 declaration** — the user decides when to jump from 0.13.x to 1.0.0
  once the packaging reach and the v1.0 hardening plan (above) are in place.

## Released versions

0.6.0 → 0.7.0 → 0.8.0 → 0.9.0 → 0.10.0 → 0.11.0 → 0.12.0 → 0.13.0 (all on PyPI;
v0.12.0 and v0.13.0 also have GitHub Releases with wheel + sdist).
