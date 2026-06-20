"""Tests for interactive prompts."""

from pathlib import Path
from unittest.mock import patch

import pytest

from claude_wiki.interactive import choice, confirm, configure, is_interactive, prompt
from claude_wiki.models import ProjectConfig


class TestIsInteractive:
    """Tests for is_interactive."""

    def test_is_interactive_reflects_stdin(self):
        """is_interactive returns sys.stdin.isatty()."""
        with patch("claude_wiki.interactive.sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            assert is_interactive() is True
            mock_stdin.isatty.return_value = False
            assert is_interactive() is False


class TestPrompt:
    """Tests for prompt behaviour."""

    def test_prompt_eof_returns_default(self):
        """EOFError accepts the provided default."""
        with patch("claude_wiki.interactive.input", side_effect=EOFError()):
            assert prompt("value", default="fallback") == "fallback"

    def test_prompt_eof_without_default_raises(self):
        """EOFError with no default propagates."""
        with patch("claude_wiki.interactive.input", side_effect=EOFError()):
            with pytest.raises(EOFError):
                prompt("value")

    def test_prompt_reprompts_on_invalid_input(self):
        """Invalid input loops until the validator passes."""
        with patch(
            "claude_wiki.interactive.input", side_effect=["bad", "also-bad", "good"]
        ):
            with patch("claude_wiki.interactive.print") as mock_print:
                result = prompt("value", validator=lambda x: x == "good")
                assert result == "good"
                assert mock_print.call_count == 2

    def test_prompt_accepts_default_on_empty_input(self):
        """Empty input accepts the default value."""
        with patch("claude_wiki.interactive.input", return_value=""):
            assert prompt("value", default="fallback") == "fallback"

    def test_prompt_trims_input(self):
        """Leading and trailing whitespace are stripped."""
        with patch("claude_wiki.interactive.input", return_value="  answer  "):
            assert prompt("value") == "answer"


class TestChoice:
    """Tests for choice prompts."""

    def test_choice_is_case_insensitive(self):
        """Choice input is matched case-insensitively."""
        with patch("claude_wiki.interactive.input", return_value="B"):
            assert choice("pick", ["a", "b"]) == "b"

    def test_choice_returns_default(self):
        """Empty input returns the default option."""
        with patch("claude_wiki.interactive.input", return_value=""):
            assert choice("pick", ["a", "b"], default="b") == "b"


class TestConfirm:
    """Tests for confirm prompts."""

    def test_confirm_yes(self):
        """Affirmative answers return True."""
        for answer in ["y", "Y", "yes", "YES"]:
            with patch("claude_wiki.interactive.input", return_value=answer):
                assert confirm("ok?") is True

    def test_confirm_default_true(self):
        """Default True is returned on empty input."""
        with patch("claude_wiki.interactive.input", return_value=""):
            assert confirm("ok?", default=True) is True

    def test_confirm_default_false(self):
        """Default False is returned on empty input."""
        with patch("claude_wiki.interactive.input", return_value=""):
            assert confirm("ok?", default=False) is False


class TestConfigure:
    """Tests for configure."""

    def test_configure_flow_project_mode(self):
        """Full configure flow returns a ProjectConfig and repo-local hooks."""
        repo = Path("/fake/repo")
        defaults = ProjectConfig(repo_name="test")
        inputs = [
            "owner",  # repo owner
            "project",  # kb mode
            "daily",  # daily dir
            "reports",  # reports dir
            "UTC",  # timezone
            "18",  # compile hour
            "repo-local",  # hook target
        ]
        with patch("claude_wiki.interactive.input", side_effect=inputs):
            config, global_hooks = configure(repo, defaults)
            assert config.repo_owner == "owner"
            assert config.repo_name == "test"
            assert str(config.kb_dir) == "project"
            assert str(config.daily_dir) == "daily"
            assert str(config.reports_dir) == "reports"
            assert config.timezone == "UTC"
            assert config.compile_after_hour == 18
            assert global_hooks is False

    def test_configure_flow_custom_kb(self):
        """Custom KB mode prompts for a path."""
        repo = Path("/fake/repo")
        defaults = ProjectConfig(repo_name="test")
        inputs = [
            "local",  # owner
            "custom",  # kb mode
            "my-kb",  # custom path
            "daily",  # daily dir
            "reports",  # reports dir
            "UTC",  # timezone
            "9",  # compile hour
            "global",  # hook target
        ]
        with patch("claude_wiki.interactive.input", side_effect=inputs):
            config, global_hooks = configure(repo, defaults)
            assert str(config.kb_dir) == "my-kb"
            assert global_hooks is True

    def test_configure_reprompts_invalid_hour(self):
        """Invalid compile hour input triggers re-prompting."""
        repo = Path("/fake/repo")
        defaults = ProjectConfig(repo_name="test")
        inputs = [
            "local",
            "project",
            "daily",
            "reports",
            "UTC",
            "not-a-number",
            "25",
            "12",
            "repo-local",
        ]
        with patch("claude_wiki.interactive.input", side_effect=inputs):
            config, _ = configure(repo, defaults)
            assert config.compile_after_hour == 12
