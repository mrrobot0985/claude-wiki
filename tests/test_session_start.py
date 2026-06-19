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


class TestSessionStartEdgeCases:
    """Tests for error handling and boundary conditions."""

    def _repo_with_lock(self, repo: Path, extra: dict | None = None) -> None:
        """Write a minimal .claude-wiki.lock in the repo."""
        data = {"repo_name": "repo", "repo_owner": "owner"}
        if extra:
            data.update(extra)
        (repo / ".claude-wiki.lock").write_text(json.dumps(data))

    def test_corrupt_lock_file_is_handled_gracefully(self, monkeypatch, capsys):
        """A corrupt .claude-wiki.lock does not crash the hook."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text("not-json")
            monkeypatch.chdir(repo)

            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "(empty - no articles compiled yet)" in context
            assert "(no recent daily log)" in context

    def test_kb_root_resolution_error_uses_placeholder(self, monkeypatch, capsys):
        """If resolving the KB root fails, the index placeholder is used."""
        from claude_wiki.config import ConfigManager

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._repo_with_lock(repo, {"kb_dir": "knowledge"})
            (repo / "knowledge").mkdir()
            (repo / "knowledge" / "index.md").write_text("# Index")

            monkeypatch.chdir(repo)

            def _raise(*_args, **_kwargs):
                raise RuntimeError("kb root unavailable")

            monkeypatch.setattr(ConfigManager, "get_kb_root", _raise)

            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "(empty - no articles compiled yet)" in context

    def test_daily_log_resolution_error_uses_placeholder(self, monkeypatch, capsys):
        """If reading the recent daily log fails, a placeholder is shown."""
        import claude_wiki.hook_handlers.session_start as session_start_mod

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._repo_with_lock(repo, {"kb_dir": "knowledge", "daily_dir": "daily"})
            (repo / "knowledge").mkdir()
            (repo / "knowledge" / "index.md").write_text("# Index")

            monkeypatch.chdir(repo)

            def _raise_daily(_path):
                raise RuntimeError("daily unreadable")

            monkeypatch.setattr(
                session_start_mod,
                "_get_recent_daily_log",
                _raise_daily,
            )

            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "(no recent daily log)" in context

    def test_global_summary_error_is_suppressed(self, monkeypatch, capsys):
        """A failure building the global summary is silently suppressed."""
        from claude_wiki.global_index import GlobalIndexManager

        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._repo_with_lock(repo, {"kb_dir": "knowledge", "daily_dir": "daily"})
            (repo / "knowledge").mkdir()
            (repo / "knowledge" / "index.md").write_text("# Index")
            (repo / "daily").mkdir()
            today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            (repo / "daily" / f"{today}.md").write_text("## Log")

            monkeypatch.chdir(repo)

            def _raise_global(*_args, **_kwargs):
                raise RuntimeError("global index down")

            monkeypatch.setattr(GlobalIndexManager, "compact_summary", _raise_global)

            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "# Index" in context
            assert "## Log" in context
            assert "## Global Knowledge Bases" not in context

    def test_short_context_is_not_truncated(self, monkeypatch, capsys):
        """A context well below the limit keeps all sections and no truncation marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            self._repo_with_lock(repo, {"kb_dir": "knowledge", "daily_dir": "daily"})
            (repo / "knowledge").mkdir()
            (repo / "knowledge" / "index.md").write_text("# Tiny index")
            (repo / "daily").mkdir()
            today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
            (repo / "daily" / f"{today}.md").write_text("Small daily note.")

            monkeypatch.chdir(repo)

            exit_code = _session_start([])
            captured = capsys.readouterr()

            assert exit_code == 0
            output = json.loads(captured.out)
            context = output["hookSpecificOutput"]["additionalContext"]
            assert "...(truncated)" not in context
            assert "# Tiny index" in context
            assert "Small daily note." in context
