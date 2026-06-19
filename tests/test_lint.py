"""Tests for the kb lint command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_kb.cli import main
from claude_kb.commands.lint import _Issue


class TestLintStructural:
    """Structural checks run without any LLM calls."""

    def _repo_and_kb(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        marker = repo / ".claude-wiki.json"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "repo",
                    "repo_owner": "local",
                    "kb_dir": str(kb_root),
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        return repo, kb_root

    @pytest.fixture(autouse=True)
    def fixed_today(self) -> None:
        with patch("claude_kb.commands.lint._today_iso", return_value="2026-06-19"):
            yield

    def test_broken_links(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A wikilink with no target is reported as an error."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        (concepts / "python.md").write_text("See [[missing-target]] for details.")

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Results: 1 errors" in captured.out
        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "Broken link:" in report
        assert "[[missing-target]]" in report

    def test_orphan_pages(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An article with no inbound links is reported as a warning."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "orphan.md").write_text(long_text)

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Results: 0 errors, 1 warnings" in captured.out
        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "Orphan page:" in report

    def test_orphan_sources(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Daily logs absent from the ingested state are reported."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        daily = repo / "daily"
        daily.mkdir()
        (daily / "2026-06-18.md").write_text("# Log")
        (kb_root / "state.json").write_text('{"ingested": {}}')

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        main(["lint", "--structural-only"])

        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "Uncompiled daily log:" in report

    def test_stale_articles(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Daily logs with a mismatched hash are reported as stale."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        daily = repo / "daily"
        daily.mkdir()
        (daily / "2026-06-18.md").write_text("# Log")
        state = {"ingested": {"2026-06-18.md": {"hash": "0000000000000000"}}}
        (kb_root / "state.json").write_text(json.dumps(state))

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        main(["lint", "--structural-only"])

        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "Stale:" in report

    def test_sparse_articles(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Articles below the word threshold are reported as suggestions."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        (concepts / "short.md").write_text("Too few words.")

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        exit_code = main(["lint", "--structural-only"])

        assert exit_code == 0
        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "Sparse article:" in report

    def test_clean_kb_returns_zero(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A healthy KB with mutual links and long articles reports no issues."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "a.md").write_text(long_text + "\n[[concepts/b]]")
        (concepts / "b.md").write_text(long_text + "\n[[concepts/a]]")

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Results: 0 errors, 0 warnings, 0 suggestions" in captured.out
        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "All checks passed" in report

    def test_report_saved_location(self, monkeypatch, tmp_path: Path) -> None:
        """The report is written to reports/lint-YYYY-MM-DD.md under the KB root."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        main(["lint", "--structural-only"])

        report_path = kb_root / "reports" / "lint-2026-06-19.md"
        assert report_path.exists()


class TestLintLLM:
    """The LLM contradiction check is included in full lint mode."""

    def _repo_and_kb(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        marker = repo / ".claude-wiki.json"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "repo",
                    "repo_owner": "local",
                    "kb_dir": str(kb_root),
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        return repo, kb_root

    @pytest.fixture(autouse=True)
    def fixed_today(self) -> None:
        with patch("claude_kb.commands.lint._today_iso", return_value="2026-06-19"):
            yield

    def test_structural_only_skips_llm(self, monkeypatch, tmp_path: Path) -> None:
        """--structural-only never invokes the LLM check."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        with patch("claude_kb.commands.lint._run_llm_checks") as mock_llm:
            main(["lint", "--structural-only"])
            mock_llm.assert_not_called()

    def test_full_lint_includes_contradictions(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Full lint merges LLM contradiction findings into the report."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "a.md").write_text(long_text)
        (concepts / "b.md").write_text(long_text + "\n[[concepts/a]]")

        monkeypatch.chdir(repo)
        monkeypatch.setenv("CLAUDE_WIKI_PROJECT_DIR", str(kb_root))

        fake_issue = _Issue(
            severity="warning",
            check="contradiction",
            file="(cross-article)",
            detail="CONTRADICTION: a vs b - conflicting advice",
        )
        with patch(
            "claude_kb.commands.lint._run_llm_checks", return_value=[fake_issue]
        ):
            exit_code = main(["lint"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "2 warnings" in captured.out
        report = (kb_root / "reports" / "lint-2026-06-19.md").read_text()
        assert "CONTRADICTION: a vs b" in report


class TestLintHandlerErrors:
    """Error handling outside of the checks themselves."""

    def test_lint_outside_repo(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Running lint outside any repo prints an error and exits 1."""
        monkeypatch.chdir(tmp_path)

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Not in a git repository" in captured.err
