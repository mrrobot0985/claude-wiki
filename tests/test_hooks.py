"""Tests for claude_wiki.hooks entry point and handler registry."""

from __future__ import annotations

import sys

import pytest

from claude_wiki import hooks


class TestHooksMain:
    """Tests for hooks.main() dispatch and argument handling."""

    def test_main_uses_sys_argv_when_argv_is_none(self, monkeypatch, mocker) -> None:
        """When argv is None, main falls back to sys.argv[1:]."""
        monkeypatch.setattr(sys, "argv", ["claude-wiki-hook", "SessionStart"])
        fake_handler = mocker.Mock(return_value=42)
        monkeypatch.setattr(
            "claude_wiki.hook_handlers.session_start._session_start",
            fake_handler,
        )

        result = hooks.main(None)

        assert result == 42
        fake_handler.assert_called_once_with([])

    def test_main_prints_usage_and_returns_one_when_no_args(
        self, monkeypatch, capsys
    ) -> None:
        """Empty argv prints usage to stderr and returns 1."""
        monkeypatch.setattr(sys, "argv", ["claude-wiki-hook"])
        result = hooks.main([])
        captured = capsys.readouterr()

        assert result == 1
        assert "Usage:" in captured.err
        assert "SessionStart|SessionEnd|PreCompact" in captured.err

    @pytest.mark.parametrize("event", ["SessionStart", "SessionEnd", "PreCompact"])
    def test_main_dispatches_to_known_handler(
        self, event: str, monkeypatch, mocker
    ) -> None:
        """Each supported event is routed to its registered handler."""
        fake_handler = mocker.Mock(return_value=0)
        handler_paths = {
            "SessionStart": "claude_wiki.hook_handlers.session_start._session_start",
            "SessionEnd": "claude_wiki.hook_handlers.session_end._handle_session_end",
            "PreCompact": "claude_wiki.hook_handlers.pre_compact.handler",
        }
        monkeypatch.setattr(handler_paths[event], fake_handler)

        result = hooks.main([event, "--flag", "value"])

        assert result == 0
        fake_handler.assert_called_once_with(["--flag", "value"])

    def test_main_returns_handler_exit_code(self, monkeypatch, mocker) -> None:
        """main returns the integer returned by the selected handler."""
        fake_handler = mocker.Mock(return_value=7)
        monkeypatch.setattr(
            "claude_wiki.hook_handlers.session_start._session_start",
            fake_handler,
        )

        result = hooks.main(["SessionStart"])

        assert result == 7

    def test_main_rejects_unknown_event(self, capsys) -> None:
        """An unrecognized event prints an error and returns 1."""
        result = hooks.main(["NotAnEvent", "extra"])
        captured = capsys.readouterr()

        assert result == 1
        assert "Unknown hook event: NotAnEvent" in captured.err

    def test_main_returns_zero_when_no_handler_registered(self, monkeypatch) -> None:
        """A known event with no registered handler exits cleanly with 0."""
        monkeypatch.setattr(hooks, "_load_handlers", lambda _handlers: None)

        result = hooks.main(["SessionStart"])

        assert result == 0


class TestLoadHandlers:
    """Tests for _load_handlers explicit registry."""

    def test_load_handlers_registers_all_handlers(self) -> None:
        """All handler modules from the explicit registry are registered."""
        handlers: dict[str, hooks._Handler] = {}

        hooks._load_handlers(handlers)

        assert set(handlers.keys()) == {"SessionStart", "SessionEnd", "PreCompact"}

    def test_load_handlers_propagates_import_failure(self, monkeypatch) -> None:
        """A broken handler module import raises instead of being swallowed."""
        from claude_wiki import hook_handlers as handlers_pkg

        def fake_get_handler_modules() -> list[str]:
            return ["claude_wiki.hook_handlers.nonexistent_broken_module_xyz"]

        monkeypatch.setattr(
            handlers_pkg, "get_handler_modules", fake_get_handler_modules
        )

        with pytest.raises(ImportError):
            hooks._load_handlers({})
