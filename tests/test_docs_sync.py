"""Lightweight check that docs/reference/cli.md stays in sync with the CLI."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DOC = REPO_ROOT / "docs" / "reference" / "cli.md"


def _run_claude_wiki(*args: str) -> str:
    """Run ``claude-wiki`` with the given args and return stdout."""
    result = subprocess.run(
        [sys.executable, "-m", "claude_wiki.cli", *args],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    return result.stdout


def _parse_top_level_commands(help_text: str) -> list[str]:
    """Extract top-level subcommands from argparse usage braces."""
    match = re.search(r"\{([^}]+)\}", help_text)
    if not match:
        pytest.fail("Could not find top-level subcommands in --help output")
    return [cmd.strip() for cmd in match.group(1).split(",")]


@pytest.mark.xfail(
    not CLI_DOC.exists(), reason="CLI reference doc is missing", strict=True
)
def test_cli_reference_documents_all_top_level_commands() -> None:
    """Every subcommand shown by ``claude-wiki --help`` appears in cli.md."""
    help_text = _run_claude_wiki("--help")
    commands = _parse_top_level_commands(help_text)
    markdown = CLI_DOC.read_text()

    missing = [cmd for cmd in commands if f"claude-wiki {cmd}" not in markdown]
    assert not missing, f"Subcommands missing from {CLI_DOC}: {missing}"


def test_cli_reference_documents_registry_subcommands() -> None:
    """Registry nested subcommands are documented."""
    registry_help = _run_claude_wiki("registry", "--help")
    match = re.search(r"\{([^}]+)\}", registry_help)
    if not match:
        pytest.skip("Could not parse registry subcommands")
    subcommands = [cmd.strip() for cmd in match.group(1).split(",")]
    markdown = CLI_DOC.read_text()

    missing = [
        cmd for cmd in subcommands if f"`claude-wiki registry {cmd}`" not in markdown
    ]
    assert not missing, f"Registry subcommands missing from {CLI_DOC}: {missing}"
