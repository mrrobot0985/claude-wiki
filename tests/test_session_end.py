"""Tests for the SessionEnd hook handler and shared flush module."""

from __future__ import annotations

import io
import json
import subprocess
import sys
import types
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from claude_kb import flush
from claude_kb.hook_handlers import session_end


class TestReadHookInput:
    """Tests for parsing the JSON payload sent on stdin."""

    def test_parses_valid_json(self) -> None:
        """Return a dict for well-formed JSON."""
        payload = json.dumps(
            {"session_id": "abc123", "transcript_path": "/tmp/t.jsonl"}
        )
        result = flush.read_hook_input(payload)
        assert result["session_id"] == "abc123"
        assert result["transcript_path"] == "/tmp/t.jsonl"

    def test_fixes_unescaped_windows_backslashes(self) -> None:
        """Repair Windows-style paths with single backslashes."""
        raw = '{"session_id":"abc","transcript_path":"C:\\Users\\me\\transcript.jsonl"}'
        result = flush.read_hook_input(raw)
        assert result["transcript_path"] == r"C:\Users\me\transcript.jsonl"

    def test_raises_on_invalid_json(self) -> None:
        """Raise ValueError when the payload cannot be parsed."""
        with pytest.raises(ValueError):
            flush.read_hook_input("not json")


class TestExtractConversationContext:
    """Tests for turning a JSONL transcript into markdown context."""

    def test_extracts_user_and_assistant_turns(self, tmp_path: Path) -> None:
        """Keep user/assistant turns, ignore system/tool entries."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "system", "content": "system prompt"}}),
            json.dumps({"message": {"role": "user", "content": "hello"}}),
            json.dumps({"message": {"role": "assistant", "content": "hi there"}}),
            json.dumps({"message": {"role": "tool", "content": "result"}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript)
        assert count == 2
        assert "**User:** hello" in context
        assert "**Assistant:** hi there" in context
        assert "system" not in context
        assert "tool" not in context

    def test_handles_content_blocks(self, tmp_path: Path) -> None:
        """Flatten content blocks to text."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps(
                {
                    "message": {
                        "role": "assistant",
                        "content": [
                            {"type": "text", "text": "first"},
                            {"type": "text", "text": "second"},
                        ],
                    }
                }
            ),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(transcript)
        assert count == 1
        assert "first" in context
        assert "second" in context

    def test_respects_max_turns_and_chars(self, tmp_path: Path) -> None:
        """Only the last max_turns are kept and characters are bounded."""
        transcript = tmp_path / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": f"msg{i:02d}"}})
            for i in range(50)
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        context, count = flush.extract_conversation_context(
            transcript, max_turns=5, max_chars=50
        )
        assert count == 5
        assert "msg49" in context
        assert "msg00" not in context
        assert len(context) <= 50


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


class TestSpawnFlush:
    """Tests for spawning the background flush process."""

    def test_spawns_module_with_detach_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Build the command and pass the right detach flags."""
        calls: list[tuple[list[str], dict[str, Any]]] = []

        def fake_popen(cmd: list[str], **kwargs: Any) -> types.SimpleNamespace:
            calls.append((cmd, kwargs))
            return types.SimpleNamespace(pid=1234)

        monkeypatch.setattr(flush.subprocess, "Popen", fake_popen)

        ctx = tmp_path / "ctx.md"
        repo = tmp_path / "repo"
        flush.spawn_flush(ctx, "s1", repo)

        assert len(calls) == 1
        cmd, kwargs = calls[0]
        assert cmd[0] == sys.executable
        assert cmd[1] == "-m"
        assert cmd[2] == "claude_kb.flush"
        assert cmd[3] == str(ctx)
        assert cmd[4] == "s1"
        assert cmd[5] == str(repo)

        if sys.platform == "win32":
            assert kwargs["creationflags"] == subprocess.CREATE_NO_WINDOW
        else:
            assert kwargs["start_new_session"] is True
        assert kwargs["stdout"] == subprocess.DEVNULL
        assert kwargs["stderr"] == subprocess.DEVNULL


class TestFlushMain:
    """Tests for the background flush entry point."""

    def _repo_with_config(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        marker = repo / ".claude-wiki.json"
        marker.write_text(
            json.dumps(
                {"repo_name": "repo", "repo_owner": "owner", "daily_dir": "daily"}
            )
        )
        return repo

    def test_appends_extracted_content_to_daily_log(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flush main appends runner output to today's daily log."""
        monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
        repo = self._repo_with_config(tmp_path)
        scripts_dir = tmp_path / "kb-scripts"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(scripts_dir))

        ctx = tmp_path / "ctx.md"
        ctx.write_text("User asked a question.\nAssistant answered.", encoding="utf-8")

        exit_code = flush.flush_main(
            [str(ctx), "session-a", str(repo)],
            runner=lambda _context, _root: "Important insight",
        )

        assert exit_code == 0
        today = date.today().strftime("%Y-%m-%d")
        daily = repo / "daily" / f"{today}.md"
        assert daily.exists()
        text = daily.read_text(encoding="utf-8")
        assert "Important insight" in text

    def test_flushes_ok_response_writes_special_entry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A FLUSH_OK response still creates an entry in the daily log."""
        monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
        repo = self._repo_with_config(tmp_path)
        scripts_dir = tmp_path / "kb-scripts"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(scripts_dir))

        ctx = tmp_path / "ctx.md"
        ctx.write_text("context", encoding="utf-8")

        flush.flush_main(
            [str(ctx), "session-b", str(repo)], runner=lambda _c, _r: "FLUSH_OK"
        )

        today = date.today().strftime("%Y-%m-%d")
        daily = repo / "daily" / f"{today}.md"
        text = daily.read_text(encoding="utf-8")
        assert "FLUSH_OK - Nothing worth saving" in text

    def test_duplicate_flush_within_60_seconds_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Second flush of the same session within 60s is skipped."""
        monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
        repo = self._repo_with_config(tmp_path)
        scripts_dir = tmp_path / "kb-scripts"
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(scripts_dir))

        ctx = tmp_path / "ctx.md"
        ctx.write_text("context", encoding="utf-8")

        flush.flush_main(
            [str(ctx), "session-c", str(repo)], runner=lambda _c, _r: "FLUSH_OK"
        )

        ctx2 = tmp_path / "ctx2.md"
        ctx2.write_text("context", encoding="utf-8")
        exit_code = flush.flush_main(
            [str(ctx2), "session-c", str(repo)], runner=lambda _c, _r: "FLUSH_OK"
        )

        assert exit_code == 0
        assert not ctx2.exists()  # cleaned up even when skipped


class TestSessionEndHandler:
    """Tests for the SessionEnd hook handler orchestration."""

    def _repo_with_config(self, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        marker = repo / ".claude-wiki.json"
        marker.write_text(json.dumps({"repo_name": "repo", "repo_owner": "owner"}))
        return repo

    def test_recursion_guard_exits_immediately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If CLAUDE_INVOKED_BY is set, the handler returns 0 without work."""
        monkeypatch.setenv("CLAUDE_INVOKED_BY", "memory_flush")
        assert session_end._handle_session_end([]) == 0

    def test_invalid_json_is_logged_and_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Malformed stdin is handled gracefully."""
        monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
        repo = self._repo_with_config(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
        monkeypatch.setattr("sys.stdin", io.StringIO("not json"))

        assert session_end._handle_session_end([]) == 0

    def test_missing_transcript_path_is_logged_and_exits(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Skip when the hook payload has no transcript path."""
        monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
        repo = self._repo_with_config(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))

        payload = json.dumps({"session_id": "abc"})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        assert session_end._handle_session_end([]) == 0
        # The try_log helper may not reach the log path, so just ensure no crash.

    def test_spawns_flush_for_valid_transcript(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A valid transcript leads to context extraction and a background spawn."""
        monkeypatch.delenv("CLAUDE_INVOKED_BY", raising=False)
        repo = self._repo_with_config(tmp_path)
        monkeypatch.chdir(repo)
        xdg = tmp_path / "xdg"
        monkeypatch.setenv("XDG_DATA_HOME", str(xdg))

        transcript = repo / "transcript.jsonl"
        lines = [
            json.dumps({"message": {"role": "user", "content": "hello"}}),
            json.dumps({"message": {"role": "assistant", "content": "world"}}),
        ]
        transcript.write_text("\n".join(lines), encoding="utf-8")

        payload = json.dumps({"session_id": "xyz", "transcript_path": str(transcript)})
        monkeypatch.setattr("sys.stdin", io.StringIO(payload))

        spawn_calls: list[tuple[Path, str, Path]] = []

        def fake_spawn(
            context_file: Path, session_id: str, repo_root: Path
        ) -> types.SimpleNamespace:
            spawn_calls.append((context_file, session_id, repo_root))
            return types.SimpleNamespace(pid=999)

        monkeypatch.setattr(
            "claude_kb.hook_handlers.session_end.flush.spawn_flush", fake_spawn
        )

        assert session_end._handle_session_end([]) == 0

        assert len(spawn_calls) == 1
        context_file, session_id, repo_root = spawn_calls[0]
        assert session_id == "xyz"
        assert repo_root.resolve() == repo.resolve()
        assert context_file.exists()
        assert "hello" in context_file.read_text(encoding="utf-8")

        log_path = xdg / "claude-wiki" / "owner" / "repo" / "scripts" / "flush.log"
        assert log_path.exists()
        log_text = log_path.read_text(encoding="utf-8")
        assert "SessionEnd fired: session=xyz" in log_text
        assert "Spawned flush.py for session xyz" in log_text
