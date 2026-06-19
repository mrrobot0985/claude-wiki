# CI/CD Reference

Continuous integration, release automation, and supply-chain security.

______________________________________________________________________

## Workflows

Two GitHub Actions workflows live in `.github/workflows/`.

### `ci.yml` — Continuous Integration

Runs on every push to `main` and every pull request.

| Job         | Purpose                                                                |
| ----------- | ---------------------------------------------------------------------- |
| `test`      | Matrix across Python 3.12–3.14. Runs pytest, ruff, mypy, and mdformat. |
| `precommit` | Runs all pre-commit hooks on the full tree.                            |

Key features:

- **Least-privilege permissions** — `permissions: contents: read` at workflow level.
- **Concurrency control** — redundant runs on the same branch/PR are cancelled automatically.
- **Immutable action references** — every third-party action is pinned to a full 40-character commit SHA with a trailing version comment.

### `release.yml` — PyPI Publication

Triggered by pushing a tag matching `v*`.

| Step    | Detail                                                                      |
| ------- | --------------------------------------------------------------------------- |
| Build   | `uv build` produces sdist + wheel.                                          |
| Publish | `uv publish` uses PyPI Trusted Publishing (OIDC). No API tokens are stored. |

The job declares a `pypi` environment so GitHub Environment protection rules (reviewers, deployment history) can be enforced.

## Supply-Chain Hardening

### SHA Pinning

All third-party actions are pinned to immutable commit SHAs rather than mutable version tags. This prevents supply-chain attacks where a compromised tag is repointed to malicious code.

| Action                 | SHA                                        | Version |
| ---------------------- | ------------------------------------------ | ------- |
| `actions/checkout`     | `9c091bb21b7c1c1d1991bb908d89e4e9dddfe3e0` | v7.0.0  |
| `actions/setup-python` | `a309ff8b426b58ec0e2a45f0f869d46889d02405` | v6.2.0  |
| `astral-sh/setup-uv`   | `fac544c07dec837d0ccb6301d7b5580bf5edae39` | v8.2.0  |

`astral-sh/setup-uv` v8.x switched to fully immutable releases; moving tags like `@v8` no longer exist, making SHA pinning mandatory.

### Trusted Publishing

PyPI is linked to this GitHub repository via OIDC. When `release.yml` runs inside GitHub Actions with `permissions: id-token: write`, `uv publish` automatically exchanges a short-lived OIDC token for a temporary upload credential. No long-lived API tokens or passwords are stored anywhere.

Sources:

- [GitHub Actions Security Cheat Sheet — OWASP](https://cheatsheetseries.owasp.org/cheatsheets/GitHub_Actions_Security_Cheat_Sheet.html)
- [GitHub Actions 2026 Security Roadmap](https://github.blog/news-insights/product-news/whats-coming-to-our-github-actions-2026-security-roadmap/)
- [PyPI Trusted Publishers](https://docs.pypi.org/trusted-publishers/)
- [uv Publishing Guide](https://docs.astral.sh/uv/guides/publish/)
- [astral-sh/setup-uv v8.0.0 Immutable Releases](https://github.com/astral-sh/setup-uv/releases/tag/v8.0.0)

## Dependency Management

CI uses `uv sync --extra dev --frozen` instead of `uv pip install`. This guarantees the lockfile (`uv.lock`) is respected, giving bit-for-bit reproducible builds on every run.

## Maintenance

Dependabot is configured in `.github/dependabot.yml` to propose weekly grouped updates for GitHub Actions. When an action releases a security patch, Dependabot opens a PR that bumps the pinned SHA and comment, preserving the hardening model.

## Sources

- [actions/checkout v7.0.0 release](https://github.com/actions/checkout/releases/tag/v7.0.0)
- [actions/setup-python v6.2.0 release](https://github.com/actions/setup-python/releases/tag/v6.2.0)
- [astral-sh/setup-uv v8.2.0 release](https://github.com/astral-sh/setup-uv/releases/tag/v8.2.0)
- [GitHub Actions Security Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/GitHub_Actions_Security_Cheat_Sheet.html)
- [GitHub Actions 2026 Security Roadmap](https://github.blog/news-insights/product-news/whats-coming-to-our-github-actions-2026-security-roadmap/)
- [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/)
- [uv Publishing Guide](https://docs.astral.sh/uv/guides/publish/)
- [Dependabot configuration options](https://docs.github.com/en/code-security/dependabot/dependabot-version-updates/configuration-options-for-the-dependabot.yml-file)
