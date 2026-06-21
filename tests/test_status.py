"""Tests for `claude-wiki status` diagnostic command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_wiki.cli import main
from claude_wiki.factories import CLAUDE_WIKI_HOOK_COMMAND


class TestStatusCommand:
    """Diagnostic command reports repo health."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "my-project"
        repo.mkdir()
        (repo / ".git").mkdir()
        return repo

    def _install_dummy_hooks(self, repo: Path) -> None:
        local = repo / ".claude" / "settings.local.json"
        local.parent.mkdir(parents=True, exist_ok=True)
        local.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [{"hooks": []}],
                        "SessionEnd": [{"hooks": []}],
                        "PreCompact": [{"hooks": []}],
                    }
                }
            )
        )

    def _install_claude_wiki_hooks(self, settings_path: Path) -> None:
        """Write a settings file with real claude-wiki hook commands."""
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "hooks": {
                        "SessionStart": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{CLAUDE_WIKI_HOOK_COMMAND} SessionStart",
                                        "timeout": 15,
                                    }
                                ],
                            }
                        ],
                        "SessionEnd": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{CLAUDE_WIKI_HOOK_COMMAND} SessionEnd",
                                        "timeout": 10,
                                    }
                                ],
                            }
                        ],
                        "PreCompact": [
                            {
                                "matcher": "",
                                "hooks": [
                                    {
                                        "type": "command",
                                        "command": f"{CLAUDE_WIKI_HOOK_COMMAND} PreCompact",
                                        "timeout": 10,
                                    }
                                ],
                            }
                        ],
                    }
                }
            )
        )

    def _lock(self, repo: Path, **overrides: Any) -> None:
        data = {
            "repo_name": repo.name,
            "repo_owner": "local",
            "kb_dir": "project",
            "daily_dir": ".claude/daily",
            "timezone": "UTC",
            "layout_version": "2",
            **overrides,
        }
        (repo / ".claude-wiki.lock").write_text(json.dumps(data))

    def test_status_shows_ok_for_healthy_project(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        daily = repo / ".claude" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-06-20.md").write_text("# log")
        kb = repo / ".claude" / "knowledge"
        kb.mkdir(parents=True)
        (kb / "my-project.md").write_text("# index")
        (kb / "concepts").mkdir(parents=True, exist_ok=True)
        (kb / "concepts" / "foo.md").write_text("# foo")
        state = repo / ".claude" / "state"
        state.mkdir(parents=True)
        (state / "state.json").write_text(
            json.dumps({"ingested": {"2026-06-20.md": {}}})
        )
        self._install_dummy_hooks(repo)

        monkeypatch.chdir(repo)
        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "my-project" in captured.out
        assert ".claude-wiki.lock" in captured.out
        assert "1 daily" in captured.out.lower() or "1 file" in captured.out.lower()
        assert "my-project.md" in captured.out

    def test_status_warns_when_no_lock_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        monkeypatch.chdir(repo)

        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert ".claude-wiki.lock" in captured.out
        assert "missing" in captured.out.lower() or "not found" in captured.out.lower()

    def test_status_warns_when_daily_dir_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        self._install_dummy_hooks(repo)
        (repo / ".claude" / "daily").mkdir(parents=True)
        monkeypatch.chdir(repo)

        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "0" in captured.out

    def test_status_shows_kb_counts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        self._install_dummy_hooks(repo)
        kb = repo / ".claude" / "knowledge"
        kb.mkdir(parents=True)
        (kb / "my-project.md").write_text("# index")
        (kb / "concepts").mkdir(parents=True, exist_ok=True)
        (kb / "connections").mkdir(parents=True, exist_ok=True)
        (kb / "qa").mkdir(parents=True, exist_ok=True)
        (kb / "concepts" / "a.md").write_text("# a")
        (kb / "concepts" / "b.md").write_text("# b")
        (kb / "connections" / "c.md").write_text("# c")
        (kb / "qa" / "d.md").write_text("# d")
        monkeypatch.chdir(repo)

        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "2 concepts" in captured.out or "2 concept" in captured.out
        assert "1 connections" in captured.out or "1 connection" in captured.out
        assert "1 qa" in captured.out

    def test_status_reports_missing_catalog(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        (repo / ".claude" / "knowledge").mkdir(parents=True)
        monkeypatch.chdir(repo)

        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "my-project.md" in captured.out
        assert "missing" in captured.out.lower() or "not found" in captured.out.lower()

    def test_status_reports_hooks_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        monkeypatch.chdir(repo)

        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "hook" in captured.out.lower()

    def test_status_path_override(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        self._install_dummy_hooks(repo)

        exit_code = main(["status", "--path", str(repo)])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert repo.name in captured.out

    def test_status_outside_repo_exits_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)
        exit_code = main(["status"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "not in a git repository" in captured.err.lower()

    def test_status_reports_conflict_when_local_and_global_have_claude_wiki_hooks(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """status reports an error when both repo-local and global settings contain claude-wiki hooks."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        self._install_claude_wiki_hooks(repo / ".claude" / "settings.local.json")
        self._install_claude_wiki_hooks(tmp_path / ".claude" / "settings.json")
        monkeypatch.setenv("HOME", str(tmp_path))

        exit_code = main(["status", "--path", str(repo)])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "both" in captured.out.lower()
        assert "repo-local" in captured.out.lower() or "global" in captured.out.lower()

    def test_status_json_healthy_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        daily = repo / ".claude" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-06-20.md").write_text("# log")
        kb = repo / ".claude" / "knowledge"
        kb.mkdir(parents=True)
        (kb / "my-project.md").write_text("# index")
        (kb / "concepts").mkdir(parents=True, exist_ok=True)
        (kb / "concepts" / "foo.md").write_text("# foo")
        state = repo / ".claude" / "state"
        state.mkdir(parents=True)
        (state / "state.json").write_text(
            json.dumps({"ingested": {"2026-06-20.md": {}}})
        )
        self._install_dummy_hooks(repo)

        monkeypatch.chdir(repo)
        exit_code = main(["status", "--json"])
        captured = capsys.readouterr()

        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["repo"] == "my-project"
        assert payload["total_errors"] == 0
        assert isinstance(payload["checks"], list)
        assert len(payload["checks"]) > 0
        for check in payload["checks"]:
            assert check["status"] in {"ok", "warning", "error"}
            assert isinstance(check["message"], str)
            assert "✓" not in check["message"]
            assert "⚠" not in check["message"]
            assert "✗" not in check["message"]
            assert isinstance(check["errors"], int)

    def test_status_json_missing_lock(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        monkeypatch.chdir(repo)

        exit_code = main(["status", "--json"])
        captured = capsys.readouterr()

        payload = json.loads(captured.out)
        assert payload["repo"] == "my-project"
        assert payload["total_errors"] > 0

        lock_check = next(c for c in payload["checks"] if c["name"] == "Lock file")
        assert lock_check["status"] == "error"
        assert lock_check["errors"] == 1

        skipped = [c for c in payload["checks"] if "skipped" in c["message"]]
        assert len(skipped) == 5
        assert all(c["status"] == "warning" for c in skipped)
        assert all(c["errors"] == 0 for c in skipped)

        assert exit_code == 1

    def test_status_json_corrupt_lock(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        (repo / ".claude-wiki.lock").write_text("not json")
        monkeypatch.chdir(repo)

        exit_code = main(["status", "--json"])
        captured = capsys.readouterr()

        payload = json.loads(captured.out)
        assert payload["total_errors"] > 0

        lock_check = next(c for c in payload["checks"] if c["name"] == "Lock file")
        assert lock_check["status"] == "error"
        assert "corrupt" in lock_check["message"].lower()

        skipped = [c for c in payload["checks"] if "skipped" in c["message"]]
        assert len(skipped) == 5
        assert all(c["status"] == "warning" for c in skipped)

        assert exit_code == 1

    def test_status_json_outside_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.chdir(tmp_path)

        exit_code = main(["status", "--json"])
        captured = capsys.readouterr()

        assert exit_code == 1
        payload = json.loads(captured.out)
        assert "error" in payload
        assert "not in a git repository" in payload["error"].lower()

    def test_status_human_output_unchanged(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        repo = self._repo(tmp_path)
        self._lock(repo)
        (repo / ".claude" / "daily").mkdir(parents=True)
        (repo / ".claude" / "knowledge").mkdir(parents=True)
        (repo / ".claude" / "knowledge" / "my-project.md").write_text("# index")
        self._install_dummy_hooks(repo)

        monkeypatch.chdir(repo)
        exit_code = main(["status"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "{" not in captured.out
        assert "claude-wiki status for my-project" in captured.out
        assert "Lock file" in captured.out
        assert "All checks passed." in captured.out
