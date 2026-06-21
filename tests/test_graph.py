"""Tests for `claude-wiki graph` link-topology command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from claude_wiki.cli import main


class TestGraphCommand:
    """`claude-wiki graph` reports link topology for a repo KB."""

    def _repo(self, tmp_path: Path) -> Path:
        repo = tmp_path / "wiki-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        return repo

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

    def _kb(self, repo: Path) -> Path:
        kb = repo / ".claude" / "knowledge"
        kb.mkdir(parents=True)
        return kb

    def _article(self, kb: Path, rel: str, body: str) -> None:
        path = kb / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)

    def test_empty_kb_reports_zeros(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A KB with no articles reports all-zero topology."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        self._kb(repo)
        monkeypatch.chdir(repo)

        exit_code = main(["graph"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "claude-wiki graph for wiki-repo" in captured.out
        assert "Articles: 0" in captured.out
        assert "Links:    0" in captured.out
        assert "Orphans: 0" in captured.out
        assert "Components: 0 connected" in captured.out

    def test_fully_connected_kb(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Two articles linking each other form one connected component."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        kb = self._kb(repo)
        self._article(kb, "concepts/a.md", "[[concepts/b]]")
        self._article(kb, "concepts/b.md", "[[concepts/a]]")
        monkeypatch.chdir(repo)

        exit_code = main(["graph"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Articles: 2 (2 concepts, 0 connections, 0 qa)" in captured.out
        assert "Links:    2" in captured.out
        assert "Orphans: 0" in captured.out
        assert "Components: 1 connected, largest size 2" in captured.out

    def test_fragmented_kb_reports_components(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Unlinked articles each count as their own component."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        kb = self._kb(repo)
        self._article(kb, "concepts/a.md", "# A")
        self._article(kb, "concepts/b.md", "# B")
        self._article(kb, "connections/c.md", "# C")
        monkeypatch.chdir(repo)

        exit_code = main(["graph"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Articles: 3 (2 concepts, 1 connections, 0 qa)" in captured.out
        assert "Links:    0" in captured.out
        assert "Orphans: 3" in captured.out
        assert "Components: 3 connected, largest size 1" in captured.out

    def test_hub_identified_and_ordered(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """An article linked by many others is the top hub."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        kb = self._kb(repo)
        self._article(kb, "concepts/hub.md", "# Hub")
        for name in ("a", "b", "c"):
            self._article(kb, f"concepts/{name}.md", "[[concepts/hub]]")
        monkeypatch.chdir(repo)

        exit_code = main(["graph"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Articles: 4" in captured.out
        assert "Links:    3" in captured.out
        assert "Orphans: 3" in captured.out
        assert "Hubs (top 5 by inbound links):" in captured.out
        assert "concepts/hub (3 inbound)" in captured.out

    def test_json_output_schema(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json emits the expected machine-readable topology."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        kb = self._kb(repo)
        self._article(kb, "concepts/a.md", "[[concepts/b]]")
        self._article(kb, "concepts/b.md", "[[concepts/a]]")
        self._article(kb, "qa/q.md", "# Q")
        monkeypatch.chdir(repo)

        exit_code = main(["graph", "--json"])
        captured = capsys.readouterr()

        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["repo"] == "wiki-repo"
        assert payload["articles"] == 3
        assert payload["by_subdir"] == {
            "concepts": 2,
            "connections": 0,
            "qa": 1,
        }
        assert payload["links"] == 2
        assert payload["orphans"] == ["qa/q.md"]
        assert payload["hubs"] == [
            {"article": "concepts/a", "inbound": 1},
            {"article": "concepts/b", "inbound": 1},
        ]
        assert payload["components"] == {"count": 2, "largest": 2}

    def test_path_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--path resolves the repo without cd-ing into it."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        kb = self._kb(repo)
        self._article(kb, "concepts/a.md", "# A")
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        exit_code = main(["graph", "--path", str(repo)])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "claude-wiki graph for wiki-repo" in captured.out
        assert "Articles: 1" in captured.out

    def test_outside_repo_exits_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """Running graph outside any repo prints an error and exits 1."""
        monkeypatch.chdir(tmp_path)

        exit_code = main(["graph"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Not in a git repository" in captured.err

    def test_json_outside_repo(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--json outside a repo emits a JSON error payload."""
        monkeypatch.chdir(tmp_path)

        exit_code = main(["graph", "--json"])
        captured = capsys.readouterr()

        assert exit_code == 1
        payload = json.loads(captured.out)
        assert "error" in payload
        assert "not in a git repository" in payload["error"].lower()

    def test_missing_kb_dir_exits_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """If the configured KB directory does not exist, graph exits 1."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        monkeypatch.chdir(repo)

        exit_code = main(["graph"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Knowledge base directory not found" in captured.err

    def test_top_flag_limits_hubs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--top limits the number of hubs listed."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        kb = self._kb(repo)
        self._article(kb, "concepts/hub.md", "# Hub")
        for name in ("a", "b", "c"):
            self._article(kb, f"concepts/{name}.md", "[[concepts/hub]]")
        monkeypatch.chdir(repo)

        exit_code = main(["graph", "--top", "1"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Hubs (top 1 by inbound links):" in captured.out
        assert "concepts/hub (3 inbound)" in captured.out
        assert captured.out.count("concepts/hub") == 1

    def test_top_rejects_invalid_value(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """--top validates its argument as a positive integer."""
        repo = self._repo(tmp_path)
        self._lock(repo)
        self._kb(repo)
        monkeypatch.chdir(repo)

        with pytest.raises(SystemExit) as exc_info:
            main(["graph", "--top", "0"])
        captured = capsys.readouterr()

        assert exc_info.value.code == 2
        assert "positive integer" in captured.err.lower()
