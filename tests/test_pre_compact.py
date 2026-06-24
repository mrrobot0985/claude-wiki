"""Tests for the PreCompact hook handler."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from claude_wiki import flush, hook_handlers


@pytest.fixture
def pre_compact():
    """Import the handler module with a mocked shared flush function."""
    from claude_wiki.hook_handlers import pre_compact as mod

    original = mod._spawn_flush
    mod._spawn_flush = MagicMock()
    try:
        yield mod
    finally:
        mod._spawn_flush = original


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """Create a fake repo root and make it the current working directory."""
    (tmp_path / ".git").mkdir()
    kb_root = tmp_path / "kb-root"
    monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
    return tmp_path


def _stdin(monkeypatch, data: dict | str) -> None:
    """Patch sys.stdin with JSON or raw text."""
    import io

    if isinstance(data, dict):
        payload = json.dumps(data)
    else:
        payload = data
    monkeypatch.setattr("sys.stdin", io.StringIO(payload))


def _transcript(path: Path, turns: list[tuple[str, str | list]]) -> None:
    """Write a JSONL transcript file."""
    lines = []
    for role, content in turns:
        entry: dict = {"message": {"role": role, "content": content}}
        lines.append(json.dumps(entry))
    path.write_text("\n".join(lines), encoding="utf-8")


class TestPreCompactHandler:
    """Acceptance criteria for the PreCompact hook."""

    def test_missing_transcript_path(self, pre_compact, repo, monkeypatch, caplog):
        """Skip when transcript_path is absent."""
        caplog.set_level(logging.INFO)
        _stdin(monkeypatch, {"session_id": "abc"})

        result = pre_compact.handler([])

        assert result == 0
        assert "SKIP: no transcript path" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_empty_transcript_path(self, pre_compact, repo, monkeypatch, caplog):
        """Skip when transcript_path is empty."""
        caplog.set_level(logging.INFO)
        _stdin(monkeypatch, {"session_id": "abc", "transcript_path": ""})

        result = pre_compact.handler([])

        assert result == 0
        assert "SKIP: no transcript path" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_nonexistent_transcript(self, pre_compact, repo, monkeypatch, caplog):
        """Skip when transcript file is missing."""
        caplog.set_level(logging.INFO)
        missing = repo / "missing.jsonl"
        _stdin(monkeypatch, {"session_id": "abc", "transcript_path": str(missing)})

        result = pre_compact.handler([])

        assert result == 0
        assert "SKIP: transcript missing" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_malformed_stdin(self, pre_compact, repo, monkeypatch, caplog):
        """Return an error when stdin is not valid JSON."""
        caplog.set_level(logging.INFO)
        _stdin(monkeypatch, "not-json{")

        result = pre_compact.handler([])

        assert result == 1
        assert "Failed to parse stdin" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_stdin_non_object_returns_error(
        self, pre_compact, repo, monkeypatch, caplog
    ):
        """Valid JSON that is not an object (e.g. an array) is rejected (issue #51)."""
        caplog.set_level(logging.INFO)
        _stdin(monkeypatch, '["not", "an", "object"]')

        result = pre_compact.handler([])

        assert result == 1
        assert "Failed to parse stdin" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_insufficient_turns(self, pre_compact, repo, monkeypatch, caplog):
        """Skip when conversation has fewer than 5 turns."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        _transcript(transcript, [("user", f"msg {i}") for i in range(4)])
        _stdin(monkeypatch, {"session_id": "abc", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 0
        assert "only 4 turns (min 5)" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_valid_transcript_spawns_flush(
        self, pre_compact, repo, monkeypatch, caplog, tmp_path
    ):
        """Extract context, write file, and spawn shared flush logic."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        user_turns = [("user", f"user {i}") for i in range(3)]
        assistant_turns = [("assistant", f"assistant {i}") for i in range(3)]
        _transcript(transcript, user_turns + assistant_turns)
        _stdin(monkeypatch, {"session_id": "abc", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 0
        cache_dir = tmp_path / ".claude"
        context_files = list(cache_dir.glob("flush-context-*.md"))
        assert len(context_files) == 1
        context = context_files[0].read_text(encoding="utf-8")
        assert "user 2" in context
        assert "assistant 2" in context

        assert pre_compact._spawn_flush.called
        args = pre_compact._spawn_flush.call_args.args
        assert args[0] == context_files[0]
        assert args[1] == "abc"
        assert args[2] == repo
        assert "Spawned flush" in caplog.text

    def test_text_block_content(self, pre_compact, repo, monkeypatch, caplog, tmp_path):
        """Extract text from structured content blocks."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        content = [
            {"type": "text", "text": "first"},
            {"type": "tool_result", "content": "ignored"},
            "second",
        ]
        _transcript(
            transcript,
            [("user", "hello")] * 2 + [("assistant", content)] * 3,
        )
        _stdin(monkeypatch, {"session_id": "blk", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 0
        assert pre_compact._spawn_flush.called
        cache_dir = tmp_path / ".claude"
        context_files = list(cache_dir.glob("flush-context-blk-*.md"))
        assert len(context_files) == 1
        context = context_files[0].read_text(encoding="utf-8")
        assert "first" in context
        assert "second" in context

    def test_unsupported_roles_ignored(self, pre_compact, repo, monkeypatch, caplog):
        """Only user and assistant roles count toward the turn threshold."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        _transcript(
            transcript,
            [
                ("system", "system prompt"),
                ("user", "hello"),
                ("tool", "tool result"),
                ("assistant", "hi"),
                ("user", "ok"),
            ],
        )
        _stdin(
            monkeypatch,
            {"session_id": "roles", "transcript_path": str(transcript)},
        )

        result = pre_compact.handler([])

        assert result == 0
        assert "only 3 turns (min 5)" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_recursion_guard(self, pre_compact, repo, monkeypatch):
        """Exit immediately when invoked recursively."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "memory_flush")
        _stdin(
            monkeypatch,
            {"session_id": "rec", "transcript_path": str(repo / "t.jsonl")},
        )

        result = pre_compact.handler([])

        assert result == 0
        pre_compact._spawn_flush.assert_not_called()

    def test_spawn_failure_returns_error(self, pre_compact, repo, monkeypatch, caplog):
        """Return an error when shared flush logic fails to spawn."""
        caplog.set_level(logging.INFO)
        pre_compact._spawn_flush.side_effect = RuntimeError("spawn failed")
        transcript = repo / "transcript.jsonl"
        _transcript(transcript, [("user", f"u{i}") for i in range(6)])
        _stdin(monkeypatch, {"session_id": "err", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 1
        assert "Failed to spawn flush" in caplog.text

    def test_logs_to_logs_flush_log(self, pre_compact, repo, monkeypatch, tmp_path):
        """Log messages are appended to logs/flush.log."""
        _stdin(monkeypatch, {"session_id": "log", "transcript_path": ""})

        pre_compact.handler([])

        log_file = tmp_path / ".claude" / "state" / "logs" / "flush.log"
        assert log_file.exists()
        assert "PreCompact fired" in log_file.read_text(encoding="utf-8")


class TestPreCompactEdgeCases:
    """Tests for error paths and boundary conditions."""

    def test_import_error_falls_back_to_no_spawn(self, pre_compact, monkeypatch, repo):
        """If claude_wiki.flush.spawn_flush is absent, _spawn_flush becomes None."""
        import importlib

        monkeypatch.delattr("claude_wiki.flush.spawn_flush", raising=False)
        importlib.reload(pre_compact)

        assert pre_compact._spawn_flush is None

        transcript = repo / "transcript.jsonl"
        _transcript(transcript, [("user", f"u{i}") for i in range(6)])
        _stdin(
            monkeypatch, {"session_id": "no-spawn", "transcript_path": str(transcript)}
        )

        result = pre_compact.handler([])

        assert result == 1

    def test_empty_stdin_is_tolerated(self, pre_compact, repo, monkeypatch, caplog):
        """An empty stdin payload is treated as an empty dict."""
        caplog.set_level(logging.INFO)
        _stdin(monkeypatch, "")

        result = pre_compact.handler([])

        assert result == 0
        assert "SKIP: no transcript path" in caplog.text

    def test_malformed_jsonl_and_non_dict_message_are_skipped(
        self, pre_compact, repo, monkeypatch, caplog
    ):
        """Empty lines, bad JSON, and non-dict message fields are ignored."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        lines = [
            "",
            "not-valid-json",
            json.dumps({"message": "raw text", "role": "user", "content": "fallback"}),
            json.dumps({"message": {"role": "assistant", "content": "kept"}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")
        _stdin(monkeypatch, {"session_id": "mixed", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 0
        assert "only 2 turns (min 5)" in caplog.text

    def test_context_is_truncated_when_exceeding_max_chars(
        self, pre_compact, repo, monkeypatch, caplog, tmp_path
    ):
        """Long contexts are trimmed from the end to the configured character limit."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        long_text = "x" * 600
        _transcript(
            transcript,
            [("user", f"{long_text} u{i}") for i in range(30)],
        )
        _stdin(monkeypatch, {"session_id": "long", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 0
        cache_dir = tmp_path / ".claude"
        context_files = list(cache_dir.glob("flush-context-long-*.md"))
        assert len(context_files) == 1
        context = context_files[0].read_text(encoding="utf-8")
        assert len(context) <= 15_000
        assert "u29" in context

    def test_config_load_failure_returns_error(
        self, pre_compact, repo, monkeypatch, caplog
    ):
        """Failure to locate or load the repo config returns 1."""
        from claude_wiki.config import ConfigManager
        from claude_wiki.errors import ConfigError

        caplog.set_level(logging.ERROR)

        def _raise(*_args, **_kwargs):
            raise ConfigError("config load failed")

        monkeypatch.setattr(ConfigManager, "load", _raise)
        _stdin(
            monkeypatch, {"session_id": "cfg", "transcript_path": str(repo / "t.jsonl")}
        )

        result = pre_compact.handler([])

        assert result == 1
        assert "Failed to locate repo root" in caplog.text

    def test_context_extraction_failure_returns_error(
        self, pre_compact, repo, monkeypatch, caplog
    ):
        """An exception reading the transcript returns 1."""
        caplog.set_level(logging.ERROR)
        transcript = repo / "transcript.jsonl"
        transcript.mkdir()
        _stdin(
            monkeypatch, {"session_id": "extract", "transcript_path": str(transcript)}
        )

        result = pre_compact.handler([])

        assert result == 1
        assert "Context extraction failed" in caplog.text

    def test_empty_context_skips_flush(self, pre_compact, repo, monkeypatch, caplog):
        """A transcript yielding no usable context is skipped."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        _transcript(
            transcript,
            [("system", "system prompt"), ("tool", "tool result")],
        )
        _stdin(monkeypatch, {"session_id": "empty", "transcript_path": str(transcript)})

        result = pre_compact.handler([])

        assert result == 0
        assert "SKIP: empty context" in caplog.text
        pre_compact._spawn_flush.assert_not_called()

    def test_outside_repo_transcript_path_is_rejected(
        self, pre_compact, repo, monkeypatch, caplog
    ):
        """A transcript path outside the allowed roots is rejected and logged."""
        caplog.set_level(logging.ERROR)
        outside = repo.parent / "evil.jsonl"
        outside.write_text("{}", encoding="utf-8")
        _stdin(monkeypatch, {"session_id": "outside", "transcript_path": str(outside)})

        result = pre_compact.handler([])

        assert result == 0
        assert "Rejected transcript path" in caplog.text
        pre_compact._spawn_flush.assert_not_called()


class TestPreCompactDelegation:
    """Ensure PreCompact delegates to shared flush helpers instead of duplicating."""

    def test_extract_context_delegates_to_flush(
        self, pre_compact, repo, monkeypatch, caplog, tmp_path
    ):
        """Context extraction calls flush.extract_conversation_context."""
        caplog.set_level(logging.INFO)
        transcript = repo / "transcript.jsonl"
        _transcript(transcript, [("user", f"u{i}") for i in range(6)])
        _stdin(
            monkeypatch, {"session_id": "delegate", "transcript_path": str(transcript)}
        )

        calls: list[tuple[object, dict[str, object]]] = []
        original = flush.extract_conversation_context

        def fake_extract(path: Path, **kwargs: object) -> tuple[str, int]:
            calls.append((path, kwargs))
            return original(path, **kwargs)

        monkeypatch.setattr(flush, "extract_conversation_context", fake_extract)

        result = pre_compact.handler([])

        assert result == 0
        assert len(calls) == 1
        assert calls[0][0] == transcript
        assert calls[0][1] == {
            "max_turns": pre_compact.MAX_TURNS,
            "max_chars": pre_compact.MAX_CONTEXT_CHARS,
        }
        assert "Spawned flush" in caplog.text

    def test_lightly_escaped_stdin_uses_shared_parser(
        self, pre_compact, repo, monkeypatch, caplog
    ):
        """PreCompact parses lightly-escaped JSON via flush.read_hook_input."""
        caplog.set_level(logging.INFO)
        raw = '{"session_id":"win","transcript_path":"C:\\Users\\me\\transcript.jsonl"}'

        calls: list[str] = []
        original = flush.read_hook_input

        def fake_read(text: str) -> dict[str, Any]:
            calls.append(text)
            return original(text)

        monkeypatch.setattr(flush, "read_hook_input", fake_read)

        monkeypatch.setattr("sys.stdin", io.StringIO(raw))
        result = pre_compact.handler([])

        assert result == 0
        assert len(calls) == 1
        assert r"C:\Users\me\transcript.jsonl" in caplog.text


class TestRegistration:
    """Auto-discovery contract for hook handlers."""

    def test_register_adds_pre_compact(self):
        """The module exposes a register function that adds PreCompact."""
        handlers: dict[str, object] = {}
        hook_handlers.pre_compact.register(handlers)
        assert "PreCompact" in handlers
        assert handlers["PreCompact"] is hook_handlers.pre_compact.handler
