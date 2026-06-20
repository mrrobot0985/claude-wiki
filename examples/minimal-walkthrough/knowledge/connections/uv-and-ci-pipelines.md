---
title: "uv and CI Pipelines"
concepts:
  - "uv-python-toolchain"
  - "project-mode-venv"
insight: "Replacing pip with uv in CI reduces install time by 2-3x with minimal Dockerfile changes."
created: 2026-06-20
updated: 2026-06-20
---

# uv and CI Pipelines

## Insight

Most CI pipelines spend the majority of their time installing dependencies. Switching from `pip install` to `uv pip install` inside a Docker image cuts this phase dramatically because `uv` resolves and installs in parallel and caches aggressively.

## Concepts

- \[[concepts/uv-python-toolchain]\] - the fast installer
- \[[concepts/project-mode-venv]\] - implicit environment management

## Implications

- Docker layer caching improves because `uv` installs are faster
- `uvx` can replace multi-stage builds for one-off CLI tools
