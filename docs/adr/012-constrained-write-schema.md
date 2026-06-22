# ADR-012: Drop `acceptEdits` for a Constrained Write Schema

## Status

Accepted

## Context

`compile` invokes the agent SDK with
`allowed_tools=["Read","Write","Edit","Glob","Grep"]`,
`permission_mode="acceptEdits"`, `cwd=repo_root`, `max_turns=30`
(`compile.py:261-269`) — the LLM writes KB files directly with no `kb_root` sandbox
or path-traversal guard. `query --file-back` is safer: Read/Glob/Grep only,
`cwd=kb_root`, Python slugifies + writes (`query.py:235-238`, `399-458`) — but it
returns **prose** and writes **non-atomically**, so it is the *path-confinement*
template to generalize, not to copy verbatim.

## Decision

Generalize and improve on the `query --file-back` pattern.

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

### Implementation guardrails (both reviewers)

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

## Consequences

Materially smaller attack/corruption surface (no LLM filesystem
god-mode); path traversal eliminated mechanically; structured output is easier to
validate/retry than arbitrary edits. Tradeoff: more code in compile (writer +
validator); prompt must request full replacement articles.

## Alternatives rejected

`acceptEdits` + `cwd=kb_root` (half-measure — still
allows `../evil.md` and `Edit` on catalog/log); `acceptEdits` + post-write audit
(detects corruption after the fact).
