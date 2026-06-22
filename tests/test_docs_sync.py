"""Lightweight check that docs/reference/cli.md stays in sync with the CLI."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CLI_DOC = REPO_ROOT / "docs" / "reference" / "cli.md"
INDEX_DOC = REPO_ROOT / "docs" / "index.md"
HOWTO_DIR = REPO_ROOT / "docs" / "how-to"
ADR_DIR = REPO_ROOT / "docs" / "adr"


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


def test_how_to_guides_are_linked_from_index() -> None:
    """Every docs/how-to/*.md file is referenced from docs/index.md."""
    if not INDEX_DOC.exists():
        pytest.skip("docs/index.md is missing")
    if not HOWTO_DIR.exists():
        pytest.skip("docs/how-to directory is missing")

    markdown = INDEX_DOC.read_text()
    linked = set(re.findall(r"\[.*?\]\((how-to/[^)]+)\)", markdown))
    docs_root = REPO_ROOT / "docs"
    how_to_files = {
        path.relative_to(docs_root).as_posix()
        for path in HOWTO_DIR.glob("*.md")
        if path.is_file()
    }

    missing = how_to_files - linked
    assert not missing, f"How-to guides missing from {INDEX_DOC}: {missing}"


def _parse_adr_section(index_text: str) -> tuple[set[str], set[str]]:
    """Return the ADR numbers and link targets listed under the ADR heading."""
    numbers: set[str] = set()
    links: set[str] = set()
    in_section = False
    for line in index_text.splitlines():
        if line.startswith("## "):
            if in_section:
                break
            if line.strip() == "## Architecture Decision Records":
                in_section = True
        elif in_section:
            match = re.match(r"-\s*\[ADR-(\d{3})\]\((adr/[^)]+)\)", line)
            if match:
                numbers.add(match.group(1))
                links.add(match.group(2))
    return numbers, links


def test_adr_files_are_linked_from_index() -> None:
    """Every docs/adr/*.md file has a matching [ADR-NNN] entry in docs/index.md."""
    if not INDEX_DOC.exists():
        pytest.skip("docs/index.md is missing")
    if not ADR_DIR.exists():
        pytest.skip("docs/adr directory is missing")

    index_numbers, index_links = _parse_adr_section(INDEX_DOC.read_text())

    file_numbers = {
        re.match(r"^(\d{3})-", path.name).group(1)
        for path in ADR_DIR.glob("*.md")
        if path.is_file() and re.match(r"^(\d{3})-", path.name)
    }

    missing_from_index = file_numbers - index_numbers
    assert not missing_from_index, (
        f"ADR files missing from {INDEX_DOC}: {sorted(missing_from_index)}"
    )

    docs_root = REPO_ROOT / "docs"
    dangling = {link for link in index_links if not (docs_root / link).is_file()}
    assert not dangling, f"Dangling ADR links in {INDEX_DOC}: {sorted(dangling)}"
