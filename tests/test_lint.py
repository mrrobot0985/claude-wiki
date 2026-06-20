"""Tests for the kb lint command."""

from __future__ import annotations

import builtins
import json
import sys
from collections.abc import AsyncIterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_wiki.cli import main
from claude_wiki.commands.lint import (
    _Issue,
    _check_contradictions,
    _read_all_wiki_content,
    _run_llm_checks,
    _today_iso,
    _word_count,
)


class TestLintStructural:
    """Structural checks run without any LLM calls."""

    def _repo_and_kb(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = repo / ".claude" / "knowledge"
        kb_root.mkdir(parents=True)
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "repo",
                    "repo_owner": "local",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        return repo, kb_root

    @pytest.fixture(autouse=True)
    def fixed_today(self) -> None:
        with patch("claude_wiki.commands.lint._today_iso", return_value="2026-06-19"):
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

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 1
        assert "Results: 1 errors" in captured.out
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
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

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Results: 0 errors, 1 warnings" in captured.out
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
        assert "Orphan page:" in report

    def test_orphan_sources(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Daily logs absent from the ingested state are reported."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        daily = repo / "daily"
        daily.mkdir()
        (daily / "2026-06-18.md").write_text("# Log")
        (repo / ".claude" / "state").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "state" / "state.json").write_text('{"ingested": {}}')

        monkeypatch.chdir(repo)

        main(["lint", "--structural-only"])

        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
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
        (repo / ".claude" / "state").mkdir(parents=True, exist_ok=True)
        (repo / ".claude" / "state" / "state.json").write_text(json.dumps(state))

        monkeypatch.chdir(repo)

        main(["lint", "--structural-only"])

        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
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

        exit_code = main(["lint", "--structural-only"])

        assert exit_code == 0
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
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

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Results: 0 errors, 0 warnings, 0 suggestions" in captured.out
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
        assert "All checks passed" in report

    def test_path_flag_resolves_repo_from_outside(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """`--path` targets a repo without `cd`-ing into it (issue #44)."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "a.md").write_text(long_text + "\n[[concepts/b]]")
        (concepts / "b.md").write_text(long_text + "\n[[concepts/a]]")

        # Run from an unrelated directory — only --path should find the repo.
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        exit_code = main(["lint", "--path", str(repo), "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Results: 0 errors, 0 warnings, 0 suggestions" in captured.out
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
        assert "All checks passed" in report

    def test_report_saved_location(self, monkeypatch, tmp_path: Path) -> None:
        """The report is written to reports/lint-YYYY-MM-DD.md under the KB root."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        monkeypatch.chdir(repo)

        main(["lint", "--structural-only"])

        report_path = repo / ".claude" / "reports" / "lint-2026-06-19.md"
        assert report_path.exists()

    def test_broken_links_ignores_anchor(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An anchored wikilink whose base target exists is not broken (issue #49)."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "foo.md").write_text(long_text)
        (concepts / "bar.md").write_text(long_text + "\n[[concepts/foo#Heading]]")

        monkeypatch.chdir(repo)

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Broken link" not in captured.out

    def test_orphan_counts_aliased_and_anchored_inbound(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Inbound links via [[target|alias]] and [[target#anchor]] count (issue #49)."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        # a.md is linked from b.md via an alias and an anchor; a must not be orphan.
        (concepts / "a.md").write_text(long_text + "\n[[concepts/b]]")
        (concepts / "b.md").write_text(
            long_text + "\n[[concepts/a|Alias]] [[concepts/a#section]]"
        )

        monkeypatch.chdir(repo)

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert (
            "Orphan page: no other articles link to [[concepts/a]]" not in captured.out
        )


class TestLintLLM:
    """The LLM contradiction check is included in full lint mode."""

    def _repo_and_kb(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = repo / ".claude" / "knowledge"
        kb_root.mkdir(parents=True)
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "repo",
                    "repo_owner": "local",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        return repo, kb_root

    @pytest.fixture(autouse=True)
    def fixed_today(self) -> None:
        with patch("claude_wiki.commands.lint._today_iso", return_value="2026-06-19"):
            yield

    def test_structural_only_skips_llm(self, monkeypatch, tmp_path: Path) -> None:
        """--structural-only never invokes the LLM check."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        monkeypatch.chdir(repo)

        with patch("claude_wiki.commands.lint._run_llm_checks") as mock_llm:
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

        fake_issue = _Issue(
            severity="warning",
            check="contradiction",
            file="(cross-article)",
            detail="CONTRADICTION: a vs b - conflicting advice",
        )
        with patch(
            "claude_wiki.commands.lint._run_llm_checks", return_value=[fake_issue]
        ):
            exit_code = main(["lint"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "2 warnings" in captured.out
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
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


class TestLintHelpers:
    """Direct unit tests for lint helper functions."""

    def test_word_count_excludes_frontmatter(self, tmp_path: Path) -> None:
        """Frontmatter is not counted toward the article word count."""
        article = tmp_path / "article.md"
        body = "word " * 50
        article.write_text(f"---\ntitle: test\n---\n\n{body}")

        count = _word_count(article)
        assert count == 50

    def test_read_all_wiki_content_missing_index(self, tmp_path: Path) -> None:
        """When no index exists, the reader emits a placeholder."""
        kb = tmp_path / "kb"
        kb.mkdir()
        concepts = kb / "concepts"
        concepts.mkdir()
        (concepts / "note.md").write_text("# Note")

        content = _read_all_wiki_content(kb)
        assert "## INDEX" in content
        assert "(no index)" in content
        assert "## concepts/note.md" in content

    def test_read_all_wiki_content_missing_subdirs(self, tmp_path: Path) -> None:
        """Missing KB subdirectories are silently skipped."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "repo.md").write_text("# Index")

        content = _read_all_wiki_content(kb, repo_name="repo")
        assert "## INDEX" in content
        assert "## concepts/" not in content

    def test_today_iso_invalid_timezone_fallback(self) -> None:
        """An invalid timezone falls back to UTC."""
        result = _today_iso("Not/A/Timezone")
        assert len(result) == 10
        assert result.count("-") == 2


class TestLintStructuralEdgeCases:
    """Additional structural check edge cases."""

    def _repo_and_kb(self, tmp_path: Path) -> tuple[Path, Path]:
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = repo / ".claude" / "knowledge"
        kb_root.mkdir(parents=True)
        marker = repo / ".claude-wiki.lock"
        marker.write_text(
            json.dumps(
                {
                    "repo_name": "repo",
                    "repo_owner": "local",
                    "kb_dir": "project",
                    "daily_dir": "daily",
                    "timezone": "UTC",
                }
            )
        )
        return repo, kb_root

    @pytest.fixture(autouse=True)
    def fixed_today(self) -> None:
        with patch("claude_wiki.commands.lint._today_iso", return_value="2026-06-19"):
            yield

    def test_daily_links_are_ignored(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Wikilinks pointing into daily/ are treated as valid by design."""
        repo, kb_root = self._repo_and_kb(tmp_path)
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "note.md").write_text(long_text + "\n[[daily/2026-06-18]]")

        monkeypatch.chdir(repo)

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()

        assert exit_code == 0
        assert "Results: 0 errors" in captured.out
        assert "Broken link" not in captured.out


class TestContradictionDetection:
    """Tests for the LLM-based contradiction check."""

    def _fake_sdk_module(self, response_text: str) -> Any:
        """Return a fake claude_agent_sdk module."""

        class TextBlock:
            text = response_text

        class AssistantMessage:
            content = [TextBlock()]

        class ClaudeAgentOptions:
            def __init__(
                self, *, cwd: str, allowed_tools: list[str], max_turns: int
            ) -> None:
                self.cwd = cwd
                self.allowed_tools = allowed_tools
                self.max_turns = max_turns

        async def query(*, prompt: str, options: object) -> AsyncIterator[object]:
            yield AssistantMessage()

        module = type(sys)("claude_agent_sdk")
        module.query = query
        module.AssistantMessage = AssistantMessage
        module.ClaudeAgentOptions = ClaudeAgentOptions
        module.TextBlock = TextBlock
        return module

    @contextmanager
    def _fake_sdk(self, response_text: str) -> Any:
        """Temporarily install a fake claude_agent_sdk into sys.modules."""
        fake_module = self._fake_sdk_module(response_text)
        original = sys.modules.get("claude_agent_sdk")
        sys.modules["claude_agent_sdk"] = fake_module
        try:
            yield fake_module
        finally:
            if original is None:
                sys.modules.pop("claude_agent_sdk", None)
            else:
                sys.modules["claude_agent_sdk"] = original

    @contextmanager
    def _sdk_unavailable(self) -> None:
        """Make claude_agent_sdk imports fail during the context."""
        original_import = builtins.__import__
        real_sdk = sys.modules.pop("claude_agent_sdk", None)

        def fake_import(name: str, *args: object, **kwargs: object) -> Any:
            if name == "claude_agent_sdk":
                raise ImportError("No module named 'claude_agent_sdk'")
            return original_import(name, *args, **kwargs)

        builtins.__import__ = fake_import
        try:
            yield
        finally:
            builtins.__import__ = original_import
            if real_sdk is not None:
                sys.modules["claude_agent_sdk"] = real_sdk

    def test_no_issues_response_returns_empty(self, tmp_path: Path) -> None:
        """NO_ISSUES in the LLM response produces no contradiction issues."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "repo.md").write_text("# Index")

        with self._fake_sdk("NO_ISSUES"):
            issues = _run_llm_checks(kb, repo_name="repo")

        assert issues == []

    def test_contradiction_parsed(self, tmp_path: Path) -> None:
        """A CONTRADICTION line is turned into a warning issue."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "repo.md").write_text("# Index")

        with self._fake_sdk("CONTRADICTION: a vs b - conflicting advice"):
            issues = _run_llm_checks(kb, repo_name="repo")

        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].check == "contradiction"
        assert "CONTRADICTION: a vs b" in issues[0].detail

    def test_inconsistency_parsed(self, tmp_path: Path) -> None:
        """An INCONSISTENCY line is turned into a warning issue."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "repo.md").write_text("# Index")

        with self._fake_sdk("INCONSISTENCY: a - description here"):
            issues = _run_llm_checks(kb, repo_name="repo")

        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert "INCONSISTENCY: a" in issues[0].detail

    def test_multiple_and_ignored_lines(self, tmp_path: Path) -> None:
        """Only formatted lines are parsed; other output is ignored."""
        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "repo.md").write_text("# Index")
        response = (
            "Preamble that should be ignored\n"
            "CONTRADICTION: a vs b - one\n"
            "INCONSISTENCY: c - two\n"
            "random line"
        )

        with self._fake_sdk(response):
            issues = _run_llm_checks(kb, repo_name="repo")

        assert len(issues) == 2
        details = {issue.detail for issue in issues}
        assert "CONTRADICTION: a vs b - one" in details
        assert "INCONSISTENCY: c - two" in details

    def test_sdk_import_error(self, tmp_path: Path) -> None:
        """Missing claude_agent_sdk produces a system error issue."""
        kb = tmp_path / "kb"
        kb.mkdir()

        with self._sdk_unavailable():
            issues = _run_llm_checks(kb)

        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].file == "(system)"
        assert "LLM check unavailable" in issues[0].detail

    def test_check_contradictions_async(self, tmp_path: Path) -> None:
        """_check_contradictions can be awaited and returns parsed issues."""
        import asyncio

        kb = tmp_path / "kb"
        kb.mkdir()
        (kb / "repo.md").write_text("# Index")

        with self._fake_sdk("CONTRADICTION: x vs y - async path"):
            issues = asyncio.run(_check_contradictions(kb, repo_name="repo"))

        assert len(issues) == 1
        assert "async path" in issues[0].detail

    def test_full_lint_runs_contradictions_with_sdk(
        self, monkeypatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Full CLI lint invokes the real contradiction path via the SDK."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        kb_root = tmp_path / "kb"
        kb_root.mkdir()
        marker = repo / ".claude-wiki.lock"
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
        concepts = kb_root / "concepts"
        concepts.mkdir()
        long_text = "word " * 250
        (concepts / "a.md").write_text(long_text + "\n[[concepts/b]]")
        (concepts / "b.md").write_text(long_text + "\n[[concepts/a]]")

        monkeypatch.chdir(repo)

        with (
            patch("claude_wiki.commands.lint._today_iso", return_value="2026-06-19"),
            self._fake_sdk("CONTRADICTION: a vs b - conflict"),
        ):
            exit_code = main(["lint"])

        captured = capsys.readouterr()
        assert exit_code == 0
        assert "1 warnings" in captured.out
        report = (repo / ".claude" / "reports" / "lint-2026-06-19.md").read_text()
        assert "CONTRADICTION: a vs b - conflict" in report
