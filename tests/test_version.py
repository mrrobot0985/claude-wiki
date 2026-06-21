"""Tests for the package version surface and `--version` flag."""

from __future__ import annotations

import importlib.metadata as importlib_metadata

import pytest

import claude_wiki
from claude_wiki.cli import main


def test_version_attribute_matches_installed_metadata() -> None:
    """``claude_wiki.__version__`` mirrors the installed distribution version."""
    assert claude_wiki.__version__ == importlib_metadata.version("claude-wiki")


def test_version_attribute_is_nonempty_string() -> None:
    assert isinstance(claude_wiki.__version__, str)
    assert claude_wiki.__version__.strip()


def test_version_flag_prints_version_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`claude-wiki --version` prints the version and exits 0."""
    with pytest.raises(SystemExit) as exc_info:
        main(["--version"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert claude_wiki.__version__ in captured.out


def test_version_short_flag_prints_version_and_exits_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`claude-wiki -v` is an alias for --version."""
    with pytest.raises(SystemExit) as exc_info:
        main(["-v"])
    assert exc_info.value.code == 0
    captured = capsys.readouterr()
    assert claude_wiki.__version__ in captured.out
