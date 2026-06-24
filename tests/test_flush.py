"""Tests for the shared flush module covering error-handling paths."""

from __future__ import annotations

import asyncio
import logging
import json
import subprocess
import sys
import threading
import types
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from claude_wiki import flush
from claude_wiki.models import ProjectConfig


class TestReadHookInput:
    """Tests for parsing the hook JSON payload."""

    def test_raises_when_payload_is_not_object(self) -> None:
        """A JSON array or scalar payload must be rejected."""
        with pytest.raises(ValueError, match="hook input is not a JSON object"):
            flush.read_hook_input('["not", "an", "object"]')


class TestExtractConversationContext:
    """Tests for transcript parsing edge cases."""

    def test_max_turns_zero_returns_no_turns(self, tmp_path: Path) -> None:
        """max_turns=0 must yield empty context, not all turns (issue #51)."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": "one"}}),
            json.dumps({"message": {"role": "assistant", "content": "two"}}),
            json.dumps({"message": {"role": "user", "content": "three"}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript, max_turns=0)
        assert count == 0
        assert context == ""

    def test_skips_empty_lines(self, tmp_path: Path) -> None:
        """Blank lines in the transcript are ignored."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": "hello"}}),
            "",
            json.dumps({"message": {"role": "assistant", "content": "hi"}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript)
        assert count == 2
        assert "hello" in context
        assert "hi" in context

    def test_skips_invalid_json_lines(self, tmp_path: Path) -> None:
        """Malformed JSONL lines do not crash extraction."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": "hello"}}),
            "not valid json {",
            json.dumps({"message": {"role": "assistant", "content": "hi"}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript)
        assert count == 2
        assert "hello" in context
        assert "hi" in context

    def test_falls_back_to_top_level_role_and_content(self, tmp_path: Path) -> None:
        """Use top-level role/content when message is not a dict."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": "dict message"}}),
            json.dumps(
                {"message": "not a dict", "role": "assistant", "content": "fallback"}
            ),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript)
        assert count == 2
        assert "dict message" in context
        assert "fallback" in context

    def test_handles_string_content_blocks(self, tmp_path: Path) -> None:
        """Content blocks that are plain strings are included."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "typed"},
                            "plain string",
                            {"type": "tool_result", "text": "ignored"},
                        ],
                    }
                }
            ),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript)
        assert count == 1
        assert "typed" in context
        assert "plain string" in context
        assert "ignored" not in context

    def test_rejects_transcript_exceeding_size_cap(self, tmp_path: Path) -> None:
        """Files larger than the configured byte cap are rejected."""
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_bytes(b"x" * 11)

        with pytest.raises(ValueError, match="transcript too large"):
            flush.extract_conversation_context(transcript, max_size_bytes=10)


class TestValidateTranscriptPath:
    """Tests for the transcript path security guard."""

    def test_accepts_path_inside_repo_root(self, tmp_path: Path) -> None:
        """A transcript under the repo root is allowed."""
        repo = tmp_path / "repo"
        repo.mkdir()
        transcript = repo / "transcript.jsonl"
        transcript.write_text("{}", encoding="utf-8")

        # Should not raise.
        flush.validate_transcript_path(transcript, repo)

    def test_accepts_path_inside_claude_dir(self, tmp_path: Path) -> None:
        """A transcript under Claude Code's default dir is allowed."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        transcript = claude_dir / "transcript.jsonl"
        transcript.write_text("{}", encoding="utf-8")

        flush.validate_transcript_path(
            transcript, tmp_path / "repo", claude_dir=claude_dir
        )

    def test_accepts_path_inside_default_claude_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A transcript under the default ~/.claude directory is allowed."""
        monkeypatch.setenv("HOME", str(tmp_path))
        repo = tmp_path / "repo"
        repo.mkdir()
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        transcript = claude_dir / "transcript.jsonl"
        transcript.write_text("{}", encoding="utf-8")

        flush.validate_transcript_path(transcript, repo)

    def test_rejects_absolute_path_outside_allowed_roots(self, tmp_path: Path) -> None:
        """An absolute transcript outside repo or ~/.claude is rejected."""
        repo = tmp_path / "repo"
        repo.mkdir()
        transcript = tmp_path / "evil.jsonl"
        transcript.write_text("{}", encoding="utf-8")

        with pytest.raises(ValueError, match="outside allowed roots"):
            flush.validate_transcript_path(
                transcript, repo, claude_dir=tmp_path / "claude"
            )

    def test_rejects_traversal_relative_to_repo(self, tmp_path: Path) -> None:
        """A relative path that resolves above the repo root is rejected."""
        repo = tmp_path / "repo"
        repo.mkdir()
        transcript = repo / ".." / "evil.jsonl"

        with pytest.raises(ValueError, match="outside allowed roots"):
            flush.validate_transcript_path(
                transcript, repo, claude_dir=tmp_path / "claude"
            )


class TestSanitizeSessionId:
    """Tests for the session identifier sanitizer."""

    def test_empty_session_id_is_unknown(self) -> None:
        """An empty session id falls back to unknown."""
        assert flush.sanitize_session_id("") == "unknown"

    def test_sixty_four_char_session_id_is_allowed(self) -> None:
        """Exactly 64 safe characters are accepted."""
        sid = "a" * 64
        assert flush.sanitize_session_id(sid) == sid

    def test_sixty_five_char_session_id_is_unknown(self) -> None:
        """Anything longer than 64 safe characters falls back to unknown."""
        sid = "a" * 65
        assert flush.sanitize_session_id(sid) == "unknown"

    def test_non_string_session_id_is_unknown(self) -> None:
        """Non-string values are rejected as unsafe."""
        assert flush.sanitize_session_id(None) == "unknown"  # type: ignore[arg-type]
        assert flush.sanitize_session_id(123) == "unknown"  # type: ignore[arg-type]


class TestWriteContextFile:
    """Tests for persisting extracted context."""

    def test_creates_timestamped_context_file(self, tmp_path: Path) -> None:
        """Write context to a file under the state directory."""
        state_dir = tmp_path / "state"
        context_file = flush.write_context_file(
            state_dir, "session-1", "some context", prefix="session-flush"
        )
        assert context_file.parent == state_dir
        assert context_file.name.startswith("session-flush-session-1-")
        assert context_file.read_text(encoding="utf-8") == "some context"

    def test_bad_session_id_is_sanitized_to_unknown(self, tmp_path: Path) -> None:
        """Path-traversal characters in session_id are rejected."""
        state_dir = tmp_path / "state"
        context_file = flush.write_context_file(
            state_dir, "../../../tmp/pwn", "some context", prefix="session-flush"
        )
        assert context_file.parent == state_dir
        assert "pwn" not in context_file.name
        assert context_file.name.startswith("session-flush-unknown-")
        assert context_file.read_text(encoding="utf-8") == "some context"


class TestSpawnFlush:
    """Tests for spawning the background flush process."""

    def test_uses_windows_creationflags_on_win32(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows the subprocess receives CREATE_NO_WINDOW."""
        calls: list[tuple[list[str], dict[str, Any]]] = []

        def fake_popen(cmd: list[str], **kwargs: Any) -> types.SimpleNamespace:
            calls.append((cmd, kwargs))
            return types.SimpleNamespace(pid=1234)

        monkeypatch.setattr(flush.subprocess, "Popen", fake_popen)
        monkeypatch.setattr(
            flush.subprocess, "CREATE_NO_WINDOW", 0x08000000, raising=False
        )
        monkeypatch.setattr(flush.sys, "platform", "win32")

        ctx = tmp_path / "ctx.md"
        repo = tmp_path / "repo"
        flush.spawn_flush(ctx, "s1", repo)

        assert len(calls) == 1
        _cmd, kwargs = calls[0]
        assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
        assert "start_new_session" not in kwargs


class TestLoadFlushState:
    """Tests for deduplication state I/O."""

    def test_returns_empty_dict_for_corrupt_json(self, tmp_path: Path) -> None:
        """Invalid JSON in the state file is treated as a fresh state."""
        state_file = tmp_path / "last-flush.json"
        state_file.write_text("not json", encoding="utf-8")
        assert flush.load_flush_state(state_file) == {}

    def test_returns_empty_dict_on_read_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError while reading the state file yields an empty dict."""
        state_file = tmp_path / "last-flush.json"
        state_file.write_text("{}", encoding="utf-8")

        def raise_oserror(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("read failed")

        monkeypatch.setattr(Path, "read_text", raise_oserror)
        assert flush.load_flush_state(state_file) == {}


class TestRunFlush:
    """Tests for the LLM-backed flush runner."""

    def test_run_flush_runs_async_runner(self, tmp_path: Path) -> None:
        """run_flush wraps the async SDK call synchronously."""
        called_with: list[tuple[str, Path]] = []

        async def fake_runner(context: str, repo_root: Path) -> str:
            called_with.append((context, repo_root))
            return "result"

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(flush, "_run_flush_with_sdk", fake_runner)
        repo = tmp_path / "repo"
        result = flush.run_flush("context", repo)
        monkeypatch.undo()

        assert result == "result"
        assert called_with == [("context", repo)]

    def test_sdk_happy_path_collects_text_blocks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Text blocks from AssistantMessage are concatenated into the response."""
        repo = tmp_path / "repo"

        class FakeTextBlock:
            def __init__(self, text: str) -> None:
                self.text = text

        class FakeAssistantMessage:
            def __init__(self, text: str) -> None:
                self.content = [FakeTextBlock(text)]

        class FakeResultMessage:
            pass

        async def fake_query(*_args: Any, **_kwargs: Any) -> Any:
            yield FakeAssistantMessage("summary")
            yield FakeResultMessage()

        fake_module = types.ModuleType("claude_agent_sdk")
        fake_module.query = fake_query
        fake_module.ClaudeAgentOptions = MagicMock()
        fake_module.AssistantMessage = FakeAssistantMessage
        fake_module.ResultMessage = FakeResultMessage
        fake_module.TextBlock = FakeTextBlock
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)

        result = asyncio.run(flush._run_flush_with_sdk("context", repo))
        assert result == "summary"

    def test_sdk_error_returns_error_string(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An exception from the SDK is converted to an FLUSH_ERROR response."""
        repo = tmp_path / "repo"

        async def failing_query(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("sdk failure")
            yield  # type: ignore[unreachable]

        fake_module = types.ModuleType("claude_agent_sdk")
        fake_module.query = failing_query
        fake_module.ClaudeAgentOptions = MagicMock()
        fake_module.AssistantMessage = MagicMock()
        fake_module.ResultMessage = MagicMock()
        fake_module.TextBlock = MagicMock()
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)

        result = asyncio.run(flush._run_flush_with_sdk("context", repo))
        assert result.startswith("FLUSH_ERROR:")
        assert "sdk failure" in result


class TestFlushMainErrors:
    """Tests for error paths inside the background entry point."""

    def _repo_with_config(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "layout_version": "2",
                    "repo_name": "repo",
                    "repo_owner": "owner",
                    "daily_dir": "daily",
                }
            )
        )
        return repo

    def test_missing_context_file_returns_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """flush_main returns 1 when the context file does not exist."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "")
        monkeypatch.setattr(flush, "configure_logging", lambda _path: None)
        repo = self._repo_with_config(tmp_path)
        kb_root = tmp_path / "kb-root"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        missing_ctx = tmp_path / "missing.md"
        exit_code = flush.flush_main([str(missing_ctx), "session", str(repo)])
        assert exit_code == 1

    def test_empty_context_file_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """flush_main returns 0 and deletes an empty context file."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "")
        monkeypatch.setattr(flush, "configure_logging", lambda _path: None)
        repo = self._repo_with_config(tmp_path)
        kb_root = tmp_path / "kb-root"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        ctx = tmp_path / "ctx.md"
        ctx.write_text("   \n", encoding="utf-8")
        exit_code = flush.flush_main([str(ctx), "session", str(repo)])

        assert exit_code == 0
        assert not ctx.exists()

    def test_flush_error_appends_to_daily_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An FLUSH_ERROR response is written to the daily log."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "")
        monkeypatch.setattr(flush, "configure_logging", lambda _path: None)
        repo = self._repo_with_config(tmp_path)
        kb_root = tmp_path / "kb-root"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        ctx = tmp_path / "ctx.md"
        ctx.write_text("context", encoding="utf-8")

        exit_code = flush.flush_main(
            [str(ctx), "session-err", str(repo)],
            runner=lambda _c, _r: "FLUSH_ERROR: RuntimeError: boom",
        )

        assert exit_code == 0
        today = date.today().strftime("%Y-%m-%d")
        daily = repo / "daily" / f"{today}.md"
        text = daily.read_text(encoding="utf-8")
        assert "FLUSH_ERROR: RuntimeError: boom" in text


class TestSaveFlushState:
    """Tests for the atomic flush-state writer."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """The saved JSON can be reloaded unchanged."""
        state_file = tmp_path / "last-flush.json"
        state = {"session_id": "s-1", "timestamp": 123.0}
        flush.save_flush_state(state_file, state)
        assert flush.load_flush_state(state_file) == state

    def test_atomic_failure_leaves_original_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If os.replace fails the original state file is untouched."""
        state_file = tmp_path / "last-flush.json"
        state_file.write_text('{"session_id": "original"}', encoding="utf-8")

        def raise_after_write(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(flush.os, "replace", raise_after_write)

        with pytest.raises(OSError, match="replace failed"):
            flush.save_flush_state(state_file, {"session_id": "new"})

        assert state_file.read_text(encoding="utf-8") == '{"session_id": "original"}'


class TestAppendToDailyLog:
    """Tests for the daily log append helper."""

    def test_creates_daily_log_when_missing(self, tmp_path: Path) -> None:
        """A new daily log is initialized with the expected headings."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")

        log_path = flush.append_to_daily_log("entry", repo, config)

        assert log_path.exists()
        text = log_path.read_text(encoding="utf-8")
        today = date.today().strftime("%Y-%m-%d")
        assert f"# Daily Log: {today}" in text
        assert "## Sessions" in text
        assert "entry" in text

    def test_appends_to_existing_log(self, tmp_path: Path) -> None:
        """New entries are merged after the existing content."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")
        log_path = repo / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"
        log_path.parent.mkdir(parents=True)
        log_path.write_text("# existing\n\n## Sessions\n\n", encoding="utf-8")

        flush.append_to_daily_log("entry", repo, config)

        text = log_path.read_text(encoding="utf-8")
        assert "# existing" in text
        assert "### Session" in text
        assert "entry" in text

    def test_appends_under_custom_section(self, tmp_path: Path) -> None:
        """The section name is reflected in the heading."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")

        flush.append_to_daily_log("entry", repo, config, section="Memory Flush")
        log_path = repo / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"
        text = log_path.read_text(encoding="utf-8")
        assert "### Memory Flush" in text

    def test_atomic_failure_when_missing_does_not_create_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If os.replace fails, a missing daily log is not partially created."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")
        log_path = repo / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"

        def raise_after_write(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(flush.os, "replace", raise_after_write)

        with pytest.raises(OSError, match="replace failed"):
            flush.append_to_daily_log("entry", repo, config)

        assert not log_path.exists()

    def test_atomic_failure_leaves_existing_log_intact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If os.replace fails, an existing daily log is unchanged."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")
        log_path = repo / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"
        log_path.parent.mkdir(parents=True)
        original = "# Daily Log\n\n## Sessions\n\nexisting entry\n\n"
        log_path.write_text(original, encoding="utf-8")

        def raise_after_write(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("replace failed")

        monkeypatch.setattr(flush.os, "replace", raise_after_write)

        with pytest.raises(OSError, match="replace failed"):
            flush.append_to_daily_log("new entry", repo, config)

        assert log_path.read_text(encoding="utf-8") == original

    def test_append_error_is_propagated(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OSError while appending is raised to the caller."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")

        def raise_on_replace(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("write failed")

        monkeypatch.setattr(flush.os, "replace", raise_on_replace)
        with pytest.raises(OSError, match="write failed"):
            flush.append_to_daily_log("entry", repo, config)

    def test_concurrent_appends_do_not_drop_entries(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two concurrent appends to the same daily log keep both entries.

        ``fcntl.lockf`` locks are process-level, so the test uses a thread-level
        lock stand-in to exercise the read-modify-write serialization.
        """
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")
        lock_path = tmp_path / "daily.log.lock"
        barrier = threading.Barrier(2)
        results: list[Path] = []
        exceptions: list[BaseException] = []

        thread_lock = threading.Lock()

        def fake_lockf(_fd: int, operation: int, *_args: Any, **_kwargs: Any) -> None:
            if operation == flush.fcntl.LOCK_UN:
                thread_lock.release()
                return
            if not thread_lock.acquire(blocking=False):
                raise BlockingIOError("lock busy")

        monkeypatch.setattr(flush.fcntl, "lockf", fake_lockf)

        def append(content: str) -> None:
            barrier.wait()
            try:
                results.append(
                    flush.append_to_daily_log(
                        content, repo, config, lock_path=lock_path
                    )
                )
            except BaseException as e:
                exceptions.append(e)

        t1 = threading.Thread(target=append, args=("first entry",))
        t2 = threading.Thread(target=append, args=("second entry",))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        assert not exceptions
        log_path = repo / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"
        assert all(p == log_path for p in results)
        text = log_path.read_text(encoding="utf-8")
        assert "first entry" in text
        assert "second entry" in text

    def test_lock_timeout_raises_timeout_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the lock cannot be acquired, a TimeoutError is raised."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")
        lock_path = tmp_path / "daily.log.lock"

        def busy_on_acquire(
            _fd: int, operation: int, *_args: Any, **_kwargs: Any
        ) -> None:
            if operation == flush.fcntl.LOCK_UN:
                return
            raise BlockingIOError("lock busy")

        monkeypatch.setattr(flush.fcntl, "lockf", busy_on_acquire)

        with pytest.raises(TimeoutError, match="timed out acquiring daily log lock"):
            flush.append_to_daily_log("entry", repo, config, lock_path=lock_path)

    def test_windows_platform_skips_lock(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On Windows the lock context manager is a no-op but still appends."""
        repo = tmp_path / "repo"
        config = ProjectConfig(repo_name="repo", daily_dir="daily")
        lock_path = tmp_path / "daily.log.lock"

        calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
        if getattr(flush, "fcntl", None) is not None:
            original_lockf = flush.fcntl.lockf

            def capture_lockf(*args: Any, **kwargs: Any) -> None:
                calls.append((args, kwargs))
                return original_lockf(*args, **kwargs)

            monkeypatch.setattr(flush.fcntl, "lockf", capture_lockf)
        monkeypatch.setattr(flush.sys, "platform", "win32")

        flush.append_to_daily_log("entry", repo, config, lock_path=lock_path)

        log_path = repo / "daily" / f"{date.today().strftime('%Y-%m-%d')}.md"
        assert "entry" in log_path.read_text(encoding="utf-8")
        assert not calls


class TestLoggingSanitization:
    """WARNING/ERROR logs must not leak full paths unless debug is on."""

    def _repo_with_config(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "layout_version": "2",
                    "repo_name": "repo",
                    "repo_owner": "owner",
                    "daily_dir": "daily",
                }
            )
        )
        return repo

    def test_missing_context_file_error_logs_basename_only(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """The error for a missing context file must not contain its full path."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "")
        monkeypatch.setattr(flush, "configure_logging", lambda _path: None)
        monkeypatch.delenv("CLAUDE_WIKI_DEBUG", raising=False)
        repo = self._repo_with_config(tmp_path)
        kb_root = tmp_path / "kb-root"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        missing_ctx = tmp_path / "secret" / "ctx.md"
        missing_ctx.parent.mkdir()

        with caplog.at_level(logging.ERROR, logger=flush.logger.name):
            flush.flush_main([str(missing_ctx), "session", str(repo)])

        error_msgs = [m for m in caplog.messages if "Context file not found" in m]
        assert error_msgs
        assert str(missing_ctx) not in error_msgs[0]
        assert missing_ctx.name in error_msgs[0]

    def test_debug_mode_preserves_full_path_in_logs(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When CLAUDE_WIKI_DEBUG is set, ERROR logs include the full path."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "")
        monkeypatch.setattr(flush, "configure_logging", lambda _path: None)
        monkeypatch.setenv("CLAUDE_WIKI_DEBUG", "1")
        repo = self._repo_with_config(tmp_path)
        kb_root = tmp_path / "kb-root"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        missing_ctx = tmp_path / "secret" / "ctx.md"
        missing_ctx.parent.mkdir()

        with caplog.at_level(logging.ERROR, logger=flush.logger.name):
            flush.flush_main([str(missing_ctx), "session", str(repo)])

        error_msgs = [m for m in caplog.messages if "Context file not found" in m]
        assert error_msgs
        assert str(missing_ctx) in error_msgs[0]

    def test_sdk_error_without_debug_logs_type_only(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tracebacks are omitted from ERROR logs unless CLAUDE_WIKI_DEBUG is set."""
        import logging

        monkeypatch.delenv("CLAUDE_WIKI_DEBUG", raising=False)

        repo = tmp_path / "repo"

        async def failing_query(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("sdk failure")
            yield  # type: ignore[unreachable]

        fake_module = types.ModuleType("claude_agent_sdk")
        fake_module.query = failing_query
        fake_module.ClaudeAgentOptions = MagicMock()
        fake_module.AssistantMessage = MagicMock()
        fake_module.ResultMessage = MagicMock()
        fake_module.TextBlock = MagicMock()
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)

        records: list[logging.LogRecord] = []

        def capture_error(msg: str, *args: Any, **kwargs: Any) -> None:
            records.append(logging.LogRecord("", logging.ERROR, "", 0, msg, args, None))

        monkeypatch.setattr(flush.logger, "error", capture_error)

        asyncio.run(flush._run_flush_with_sdk("context", repo))

        assert records
        assert "Traceback" not in records[0].getMessage()
        assert "RuntimeError" in records[0].getMessage()

    def test_sdk_error_with_debug_includes_traceback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tracebacks are included in ERROR logs when CLAUDE_WIKI_DEBUG is set."""
        import logging

        monkeypatch.setenv("CLAUDE_WIKI_DEBUG", "1")

        repo = tmp_path / "repo"

        async def failing_query(*_args: Any, **_kwargs: Any) -> Any:
            raise RuntimeError("sdk failure")
            yield  # type: ignore[unreachable]

        fake_module = types.ModuleType("claude_agent_sdk")
        fake_module.query = failing_query
        fake_module.ClaudeAgentOptions = MagicMock()
        fake_module.AssistantMessage = MagicMock()
        fake_module.ResultMessage = MagicMock()
        fake_module.TextBlock = MagicMock()
        monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)

        records: list[logging.LogRecord] = []

        def capture_error(msg: str, *args: Any, **kwargs: Any) -> None:
            records.append(logging.LogRecord("", logging.ERROR, "", 0, msg, args, None))

        monkeypatch.setattr(flush.logger, "error", capture_error)

        asyncio.run(flush._run_flush_with_sdk("context", repo))

        assert records
        assert "Traceback" in records[0].getMessage()
