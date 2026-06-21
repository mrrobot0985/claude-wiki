"""Packaging metadata and artifact tests.

This module verifies that the richer metadata added for the 1.0 packaging
milestone is present in ``pyproject.toml`` and that the man page and shell
completions ship in both the wheel and the source distribution.
"""

from __future__ import annotations

import subprocess
import tarfile
import tomllib
import zipfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = REPO_ROOT / "pyproject.toml"
MAN_PAGE = REPO_ROOT / "docs" / "man" / "claude-wiki.1"


@pytest.fixture(scope="module")
def pyproject_data() -> dict:
    """Parsed pyproject.toml."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def built_wheel(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the wheel once and return its path."""
    dist_dir = tmp_path_factory.mktemp("dist")
    result = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist_dir)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    wheels = list(dist_dir.glob("*.whl"))
    assert len(wheels) == 1, f"Expected one wheel, found: {wheels}"
    return wheels[0]


@pytest.fixture(scope="module")
def built_sdist(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Build the source distribution once and return its path."""
    dist_dir = tmp_path_factory.mktemp("sdist")
    result = subprocess.run(
        ["uv", "build", "--sdist", "--out-dir", str(dist_dir)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"
    sdists = list(dist_dir.glob("*.tar.gz"))
    assert len(sdists) == 1, f"Expected one sdist, found: {sdists}"
    return sdists[0]


def test_pyproject_has_new_classifiers(pyproject_data: dict) -> None:
    """The three requested classifiers are present."""
    classifiers = pyproject_data["project"]["classifiers"]
    expected = {
        "Environment :: Console",
        "Topic :: Text Processing :: General",
        "Typing :: Typed",
    }
    missing = expected - set(classifiers)
    assert not missing, f"Missing classifiers: {missing}"


def test_pyproject_has_new_urls(pyproject_data: dict) -> None:
    """The three requested project URLs are present."""
    urls = pyproject_data["project"]["urls"]
    assert urls.get("Documentation").startswith(
        "https://github.com/mrrobot0985/claude-wiki"
    )
    assert urls.get("Changelog") == (
        "https://github.com/mrrobot0985/claude-wiki/blob/main/CHANGELOG.md"
    )
    assert urls.get("Issues") == "https://github.com/mrrobot0985/claude-wiki/issues"


def test_pyproject_keeps_existing_urls(pyproject_data: dict) -> None:
    """Original Homepage/Repository/Funding URLs are preserved."""
    urls = pyproject_data["project"]["urls"]
    for key in ("Homepage", "Repository", "Funding"):
        assert key in urls, f"Missing original URL: {key}"


def test_man_page_source_exists() -> None:
    """The man page source file exists and is not empty."""
    assert MAN_PAGE.exists(), f"Missing man page source: {MAN_PAGE}"
    assert MAN_PAGE.stat().st_size > 0, f"Man page source is empty: {MAN_PAGE}"


def test_man_page_is_force_included_in_wheel_config(pyproject_data: dict) -> None:
    """The wheel build target force-includes the man page."""
    force_include = (
        pyproject_data.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("wheel", {})
        .get("force-include", {})
    )
    found = any("docs/man/claude-wiki.1" in str(src) for src in force_include.keys())
    assert found, "Man page not force-included in wheel config"


def test_man_page_appears_in_wheel(built_wheel: Path) -> None:
    """The built wheel contains the man page under the data directory."""
    with zipfile.ZipFile(built_wheel) as whl:
        names = whl.namelist()
    man_files = [n for n in names if "claude-wiki.1" in n]
    assert man_files, "Man page missing from wheel"


def test_sdist_contains_completions_and_man_page(built_sdist: Path) -> None:
    """The source distribution includes shell completions and the man page."""
    with tarfile.open(built_sdist, "r:gz") as tar:
        names = tar.getnames()

    completion_files = {
        "completions/claude-wiki.bash",
        "completions/claude-wiki.zsh",
        "completions/claude-wiki.fish",
    }
    missing_completions = {
        name for name in completion_files if not any(n.endswith(name) for n in names)
    }
    assert not missing_completions, (
        f"Missing completions in sdist: {missing_completions}"
    )

    assert any(n.endswith("docs/man/claude-wiki.1") for n in names), (
        "Man page missing from sdist"
    )


def test_man_page_documents_current_subcommands() -> None:
    """The man page lists every current subcommand and key new flags."""
    text = MAN_PAGE.read_text(encoding="utf-8")
    # Normalise roff escaped hyphens so the source can use standard \- form.
    normalized = text.replace("\\-", "-")

    subcommands = {
        "init",
        "migrate",
        "compile",
        "query",
        "lint",
        "register",
        "registry",
        "rename-catalog",
        "status",
        "tags",
    }
    missing_subcommands = {cmd for cmd in subcommands if cmd not in normalized}
    assert not missing_subcommands, (
        f"Missing subcommands in man page: {missing_subcommands}"
    )

    key_flags = ("--fix", "--continue-on-error")
    missing_flags = {flag for flag in key_flags if flag not in normalized}
    assert not missing_flags, f"Missing flags in man page: {missing_flags}"
