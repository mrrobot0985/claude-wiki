"""Unit tests for git remote owner inference."""

from pathlib import Path
from typing import Any
from unittest.mock import patch

from claude_wiki.git_utils import infer_repo_owner


class _Result:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, stdout: str, returncode: int) -> None:
        self.stdout = stdout
        self.returncode = returncode


class TestInferRepoOwner:
    """Tests for infer_repo_owner parsing and fallbacks."""

    def _mock_run(self, stdout: str, returncode: int = 0) -> Any:
        """Return a mock subprocess.run result."""
        return _Result(stdout, returncode)

    def test_https_url(self) -> None:
        """HTTPS GitHub URL yields owner."""
        result = self._mock_run("https://github.com/mrrobot0985/claude-wiki.git\n")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "mrrobot0985"

    def test_https_url_without_git_suffix(self) -> None:
        """HTTPS URL without .git suffix yields owner."""
        result = self._mock_run("https://github.com/mrrobot0985/claude-wiki")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "mrrobot0985"

    def test_ssh_url(self) -> None:
        """SSH GitHub URL yields owner."""
        result = self._mock_run("git@github.com:mrrobot0985/claude-wiki.git\n")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "mrrobot0985"

    def test_ssh_url_without_git_suffix(self) -> None:
        """SSH URL without .git suffix yields owner."""
        result = self._mock_run("git@gitlab.com:acme/project")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "acme"

    def test_no_remote(self) -> None:
        """git returns non-zero when there is no origin remote."""
        result = self._mock_run("", returncode=2)
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"

    def test_unparsable_remote(self) -> None:
        """Remote URL with no parseable owner/repo segment falls back to local."""
        result = self._mock_run("/repo.git")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"

    def test_git_not_installed(self) -> None:
        """subprocess raising FileNotFoundError falls back to local."""
        with patch(
            "claude_wiki.git_utils.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"

    def test_empty_stdout(self) -> None:
        """Empty stdout falls back to local."""
        result = self._mock_run("")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"

    def test_https_url_with_username(self) -> None:
        """HTTPS URL with embedded username still yields owner."""
        result = self._mock_run("https://user@github.com/mrrobot0985/claude-wiki.git")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "mrrobot0985"

    def test_ssh_url_no_separator(self) -> None:
        """SSH URL lacking ':' or '/' falls back to local."""
        result = self._mock_run("git@github.com")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"

    def test_ssh_url_missing_owner(self) -> None:
        """SSH URL with only a repo segment and no owner falls back to local."""
        result = self._mock_run("git@github.com:claude-wiki.git")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"

    def test_ssh_url_empty_owner(self) -> None:
        """SSH URL with a leading '/' and empty owner falls back to local."""
        result = self._mock_run("git@github.com:/claude-wiki.git")
        with patch("claude_wiki.git_utils.subprocess.run", return_value=result):
            assert infer_repo_owner(Path("/tmp/repo")) == "local"
