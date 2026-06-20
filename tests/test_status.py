"""Tests for `claude-wiki status` diagnostic command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_wiki.cli import main


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
