---
title: "uv Python Toolchain"
aliases: [uv, astral-uv]
tags: [python, tooling]
sources:
  - "daily/2026-06-20.md"
created: 2026-06-20
updated: 2026-06-20
---

# uv Python Toolchain

`uv` is Astral's Python toolchain that replaces `pip`, `virtualenv`, and `python -m venv` with a single Rust-based executable.

## Key Points

- `uv pip install` is a drop-in replacement for `pip install`
- `uv run` executes scripts inside the project virtual environment automatically
- `uvx` runs one-off tools without permanently installing them

## Details

Unlike legacy tools, `uv` caches wheels globally and resolves dependencies in Rust, making installs significantly faster. It also manages Python versions via `uv python install`.

## Related Concepts

- \[[concepts/project-mode-venv]\] - how `uv` handles virtual environments

## Sources

- daily/2026-06-20.md - initial discovery during workflow migration
