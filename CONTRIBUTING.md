# Contributing to claude-wiki

Thank you for considering a contribution. This document covers development setup,
branching conventions, and the review process.

______________________________________________________________________

## Development Setup

**Prerequisites**

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)

**Install**

```bash
uv sync --extra dev --frozen
```

**One-time per clone**

```bash
make install-precommit
```

______________________________________________________________________

## Branch Naming

All changes must go through a feature branch. Use the pattern:

```text
<type>/<description>
```

| Prefix     | Purpose                                 |
| ---------- | --------------------------------------- |
| `feat/`    | New feature or capability               |
| `fix/`     | Bug fix                                 |
| `docs/`    | Documentation only changes              |
| `refactor` | Code change that neither fixes nor adds |
| `test/`    | Adding or updating tests                |
| `chore/`   | Maintenance, dependency updates, config |
| `ci/`      | CI/CD pipeline changes                  |

Example: `feat/session-start-hook`, `fix/mypy-strict-errors`.

______________________________________________________________________

## Commit Messages

Follow [Conventional Commits](https://www.conventionalcommits.org/):

```text
<type>[(scope)]: <description>
```

Allowed types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`, `build`, `perf`.

Description must be lowercase with no trailing period.

```text
feat: add session-start hook for capability detection
fix: handle empty stdin in standards-guard hook
chore(deps): bump actions/checkout from 4 to 6
```

______________________________________________________________________

## Before Opening a Pull Request

- [ ] Branch is up to date with `main`
- [ ] `make all` passes locally (format, lint, typecheck, test, precommit)
- [ ] Tests added or updated for behavioural changes
- [ ] Docs updated for user-visible changes
- [ ] CHANGELOG.md updated under `[Unreleased]`
- [ ] Commit messages follow conventional commits

______________________________________________________________________

## Adding a Command

1. Create `src/claude_wiki/commands/<name>.py`
1. Export `def register(subparsers, handlers) -> None: ...`
1. Add tests in `tests/test_<name>.py`

Commands are auto-discovered at runtime by `cli.py`.

______________________________________________________________________

## Adding a Hook Handler

1. Create `src/claude_wiki/hook_handlers/<event>.py`
1. Export `def register(handlers) -> None: ...`
1. Add tests in `tests/test_<event>.py`

Handlers are auto-discovered at runtime by `hooks.py`.

______________________________________________________________________

## CI/CD

See [docs/reference/ci-cd.md](docs/reference/ci-cd.md) for the full security model,
SHA pinning strategy, and PyPI trusted publishing setup.
