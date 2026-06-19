"""Tests for SessionStart hook handler."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_wiki.hook_handlers.session_start import _session_start, register


class TestSessionStart:
    """Tests for kb-hook SessionStart output."""

    def test_outputs_valid_json_with_additional_context(self, monkeypatch, capsys):
        """Hook must print valid JSON containing hookSpecificOutput.additionalContext."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            monkeypatch.chdir(repo)

            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            assert "hookSpecificOutput" in output
            assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
            assert "additionalContext" in output["hookSpecificOutput"]
            assert isinstance(output["hookSpecificOutput"]["additionalContext"], str)

    def test_includes_knowledge_index_and_recent_daily_log(self, monkeypatch, capsys):
        """Context includes knowledge/index.md and the most recent daily log."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            kb = repo / "knowledge"
            kb.mkdir()
            daily = repo / "daily"
            daily.mkdir()

            (kb / "index.md").write_text("# Knowledge Index\n\n- [[Concept A]]")
            today = datetime.now(timezone.utc).astimezone()
            (daily / f"{today.strftime('%Y-%m-%d')}.md").write_text(
                "## Log\n\nConversation happened."
            )

            marker = repo / ".claude-wiki.lock"
            marker.write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "owner",
                        "kb_dir": str(kb),
                        "daily_dir": "daily",
                        "timezone": "UTC",
                    }
                )
            )

            monkeypatch.chdir(repo)
            _session_start([])
            captured = capsys.readouterr()
            output = json.loads(captured.out)

            context = output["hookSpecificOutput"]["additionalContext"]
            assert "# Knowledge Index" in context
            assert "Concept A" in context
            assert "Conversation happened." in context

    def test_uses_yesterday_log_when_today_missing(self, monkeypatch, capsys):
        """Fallback to yesterday's daily log when today's log does not exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            daily = repo / "daily"
            daily.mkdir()

            yesterday = datetime.now(timezone.utc).astimezone() - timedelta(days=1)
            (daily / f"{yesterday.strftime('%Y-%m-%d')}.md").write_text(
                "Yesterday's notes."
            )

            marker = repo / ".claude-wiki.lock"
            marker.write_text(json.dumps({"repo_name": "repo", "repo_owner": "owner"}))

            monkeypatch.chdir(repo)
            _session_start([])
            captured = capsys.readouterr()
            output = json.loads(captured.out)

            assert (
                "Yesterday's notes."
                in output["hookSpecificOutput"]["additionalContext"]
            )

    def test_truncates_long_context_to_max_chars(self, monkeypatch, capsys):
        """Context longer than 20k chars is truncated with a marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            kb = repo / "knowledge"
            kb.mkdir()

            (kb / "index.md").write_text("x" * 25_000)

            marker = repo / ".claude-wiki.lock"
            marker.write_text(
                json.dumps(
                    {
                        "repo_name": "repo",
                        "repo_owner": "owner",
                        "kb_dir": str(kb),
                    }
                )
            )

            monkeypatch.chdir(repo)
            _session_start([])
            captured = capsys.readouterr()
            output = json.loads(captured.out)

            context = output["hookSpecificOutput"]["additionalContext"]
            assert len(context) <= 20_000
            assert context.endswith("...(truncated)")

    def test_handles_missing_files_gracefully(self, monkeypatch, capsys):
        """Missing index and daily logs produce placeholders, not errors."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            marker = repo / ".claude-wiki.lock"
            marker.write_text(json.dumps({"repo_name": "repo", "repo_owner": "owner"}))

            monkeypatch.chdir(repo)
            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "(empty - no articles compiled yet)" in context
            assert "(no recent daily log)" in context

    def test_runs_outside_repo_without_error(self, monkeypatch, capsys):
        """When cwd is not inside a repo, still emit valid JSON with placeholders."""
        with tempfile.TemporaryDirectory() as tmpdir:
            monkeypatch.chdir(tmpdir)
            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
            assert "additionalContext" in output["hookSpecificOutput"]


class TestSessionStartRegistration:
    """Tests for auto-discovery registration."""

    def test_register_adds_session_start_handler(self):
        """register() maps SessionStart to a callable handler."""
        handlers: dict[str, object] = {}
        register(handlers)
        assert "SessionStart" in handlers
        assert callable(handlers["SessionStart"])
