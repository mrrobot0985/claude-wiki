---
title: "Project Mode Virtual Environment"
aliases: [project-mode, auto-venv]
tags: [python, uv]
sources:
  - "daily/2026-06-20.md"
created: 2026-06-20
updated: 2026-06-20
---

# Project Mode Virtual Environment

When `uv` detects a `pyproject.toml` in the current directory, it enters project mode and automatically creates or reuses a `.venv` directory.

## Key Points

- No manual `python -m venv .venv` required
- `uv run` activates the environment implicitly
- `.venv` is gitignored by default

## Details

Project mode keeps dependencies local and reproducible. The lock file (`uv.lock`) ensures every collaborator gets the same versions.

## Related Concepts

- \[[concepts/uv-python-toolchain]\] - the tool that provides project mode

## Sources

- daily/2026-06-20.md - migration from manual venv to uv project mode
