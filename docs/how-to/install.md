# Install

Install `claude-wiki` via PyPI, uv, or from source.

______________________________________________________________________

## With uv (recommended)

Run CLI tools without installing permanently:

```bash
uvx claude-wiki init
```

Or install into a project:

```bash
uv pip install claude-wiki
```

## From Source

```bash
git clone https://github.com/mrrobot0985/claude-wiki
cd claude-wiki
uv sync --extra dev --frozen
```

______________________________________________________________________

## Verify Installation

```bash
claude-wiki --help
claude-wiki-hook SessionStart
```

Both should produce output without errors.

## Install Git Hooks (Development)

If working from source, install the pre-commit hooks so CI checks run on every commit:

```bash
make install-precommit
```

This registers both the `pre-commit` and `commit-msg` hooks.
