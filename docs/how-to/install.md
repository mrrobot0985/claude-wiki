# Install

Install `claude-wiki` via PyPI, uv, or from source.

______________________________________________________________________

## From PyPI (recommended)

```bash
pip install claude-wiki
```

## With uv

```bash
uv pip install claude-wiki
```

Run CLI tools without installing permanently:

```bash
uvx claude-wiki init
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
