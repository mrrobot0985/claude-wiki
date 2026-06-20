"""Tests for kb query command."""

import argparse
import asyncio
import builtins
import json
import os
import tempfile
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_wiki.cli import main
from claude_wiki.commands.query import (
    _append_log,
    _extract_wikilinks,
    _file_back,
    _is_kb_empty,
    _read_kb_content,
    _run_query,
    _slugify,
    _update_index,
    register,
)
from claude_wiki.models import QueryResult


def _fake_sdk_query(answer: str) -> Callable[..., AsyncIterator[object]]:
    """Return a fake claude_agent_sdk.query async generator."""

    async def fake_query(*, prompt: str, options: object) -> AsyncIterator[object]:
        class Block:
            text = answer

        class Message:
            content = [Block()]

        yield Message()

    return fake_query


class TestQueryHelpers:
    """Unit tests for helper functions."""

    def test_slugify_simple_question(self) -> None:
        assert _slugify("How do I handle auth?") == "how-do-i-handle-auth"

    def test_slugify_long_question_truncated(self) -> None:
        long_question = "a " * 100
        slug = _slugify(long_question)
        assert len(slug) <= 80
        assert "a" in slug
        assert not slug.endswith("-")

    def test_extract_wikilinks_finds_concepts(self) -> None:
        text = "See [[concepts/auth]] and [[connections/auth-and-webhooks]]."
        assert _extract_wikilinks(text) == [
            "concepts/auth",
            "connections/auth-and-webhooks",
        ]

    def test_is_kb_empty_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            assert _is_kb_empty(kb) is True

    def test_is_kb_empty_false(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            concepts = kb / "concepts"
            concepts.mkdir()
            (concepts / "auth.md").write_text("# Auth")
            assert _is_kb_empty(kb) is False

    def test_read_kb_content_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            assert _read_kb_content(kb) == ""

    def test_read_kb_content_reads_catalog_and_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text(
                "# Index\n\n| Article | Summary |\n|---------|---------|"
            )
            concepts = kb / "concepts"
            concepts.mkdir()
            (concepts / "auth.md").write_text("# Auth\n\nUse JWT.")
            connections = kb / "connections"
            connections.mkdir()
            (connections / "auth-and-webhooks.md").write_text("# Connection")

            content = _read_kb_content(kb, repo_name="test")
            assert "## INDEX" in content
            assert "## concepts/auth.md" in content
            assert "## connections/auth-and-webhooks.md" in content


class TestRunQuery:
    """Tests for the core query logic."""

    def test_run_query_empty_kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            fake = _fake_sdk_query("should not be called")
            result = asyncio.run(
                _run_query(kb, "question", file_back=False, query_func=fake)
            )
            assert "No knowledge base found" in result.answer
            assert result.citations == []

    def test_run_query_returns_answer_with_citations(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text("# Index")
            concepts = kb / "concepts"
            concepts.mkdir()
            (concepts / "auth.md").write_text("# Auth")

            fake = _fake_sdk_query("Use [[concepts/auth]] for authentication.")
            result = asyncio.run(
                _run_query(
                    kb,
                    "how do I auth?",
                    file_back=False,
                    repo_name="test",
                    query_func=fake,
                )
            )
            assert "[[concepts/auth]]" in result.answer
            assert "concepts/auth" in result.citations


class TestFileBack:
    """Tests for filing answers back to the knowledge base."""

    def test_file_back_creates_qa_article(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text(
                "# Knowledge Base Index\n\n"
                "| Article | Summary | Compiled From | Updated |\n"
                "|---------|---------|---------------|---------|"
            )
            (kb / "log.md").write_text("# Build Log")

            result = QueryResult(
                answer="Use [[concepts/auth]] for auth.",
                citations=["concepts/auth"],
            )
            _file_back(kb, "How do I auth?", result, repo_name="test")

            qa_file = kb / "qa" / "how-do-i-auth.md"
            assert qa_file.exists()
            content = qa_file.read_text(encoding="utf-8")
            assert "Q: How do I auth?" in content
            assert "[[concepts/auth]]" in content

    def test_file_back_updates_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text(
                "# Knowledge Base Index\n\n"
                "| Article | Summary | Compiled From | Updated |\n"
                "|---------|---------|---------------|---------|"
            )

            result = QueryResult(answer="Answer", citations=["concepts/auth"])
            _file_back(kb, "Question?", result, repo_name="test")

            index = (kb / "test.md").read_text(encoding="utf-8")
            assert "[[qa/question]]" in index

    def test_file_back_appends_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "log.md").write_text("# Build Log")

            result = QueryResult(answer="Answer", citations=["concepts/auth"])
            _file_back(kb, "Question?", result, repo_name="test")

            log = (kb / "log.md").read_text(encoding="utf-8")
            assert "query | Question?" in log
            assert "[[qa/question]]" in log

    def test_file_back_no_sources(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text("# Index")
            (kb / "log.md").write_text("# Build Log")

            result = QueryResult(answer="No sources", citations=[])
            _file_back(kb, "Question?", result, repo_name="test")

            qa_file = kb / "qa" / "question.md"
            assert qa_file.exists()
            content = qa_file.read_text(encoding="utf-8")
            assert "No sources available" in content

    def test_file_back_empty_slug_falls_back(self) -> None:
        """A question that slugifies to empty must not write qa/.md (issue #48)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text("# Index")
            (kb / "log.md").write_text("# Build Log")

            result = QueryResult(answer="Answer", citations=[])
            _file_back(kb, "!!!???---", result, repo_name="test")

            assert not (kb / "qa" / ".md").exists()
            qa_files = list((kb / "qa").glob("*.md"))
            assert len(qa_files) == 1
            assert qa_files[0].name != ".md"


class TestUpdateIndexEdgeCases:
    """Tests for index update edge cases."""

    def test_update_index_skips_missing_catalog(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            _update_index(kb, "slug", "question", "2026-06-19", repo_name="test")
            assert not (kb / "test.md").exists()

    def test_update_index_appends_without_separator(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "test.md").write_text("# Index\n\nSome text")
            _update_index(kb, "slug", "question", "2026-06-19", repo_name="test")
            index = (kb / "test.md").read_text(encoding="utf-8")
            assert "[[qa/slug]]" in index


class TestAppendLogEdgeCases:
    """Tests for log append edge cases."""

    def test_append_log_skips_missing_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            _append_log(kb, "2026-06-19T12:00:00", "question", [], "slug")
            assert not (kb / "log.md").exists()


class TestQueryCommand:
    """CLI-level tests for kb query."""

    def test_register_adds_query_subparser(self) -> None:
        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers(dest="command")
        handlers: dict[str, Callable[[argparse.Namespace], int]] = {}
        register(subparsers, handlers)

        assert "query" in handlers
        args = parser.parse_args(["query", "test question"])
        assert args.question == "test question"
        assert args.file_back is False

    def test_query_cli_not_in_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            old_cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                exit_code = main(["query", "test"])
            finally:
                os.chdir(old_cwd)
            assert exit_code == 2

    def test_query_cli_path_flag_resolves_repo_from_outside(self) -> None:
        """`--path` targets a repo without `cd`-ing into it (issue #44)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))

            elsewhere = Path(tmpdir) / "elsewhere"
            elsewhere.mkdir()
            old_cwd = os.getcwd()
            try:
                os.chdir(elsewhere)
                exit_code = main(["query", "test", "--path", str(repo)])
            finally:
                os.chdir(old_cwd)
            assert exit_code == 1

    def test_query_cli_empty_kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                exit_code = main(["query", "test"])
            finally:
                os.chdir(old_cwd)
            assert exit_code == 1

    def test_query_cli_empty_kb_json(self, capsys: pytest.CaptureFixture[str]) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                exit_code = main(["query", "test", "--json"])
            finally:
                os.chdir(old_cwd)

            captured = capsys.readouterr()
            payload = json.loads(captured.out)
            assert exit_code == 1
            assert "No knowledge base found" in payload["answer"]
            assert payload["citations"] == []

    def test_query_cli_returns_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            (kb / "concepts").mkdir()
            (kb / "concepts" / "auth.md").write_text("# Auth")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch(
                        "claude_agent_sdk.query",
                        _fake_sdk_query("Use [[concepts/auth]]."),
                    ),
                ):
                    exit_code = main(["query", "how do I auth?"])
            finally:
                os.chdir(old_cwd)
            assert exit_code == 0

    def test_query_cli_file_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            (kb / "concepts").mkdir()
            (kb / "concepts" / "auth.md").write_text("# Auth")
            (kb / "log.md").write_text("# Build Log")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch(
                        "claude_agent_sdk.query",
                        _fake_sdk_query("Use [[concepts/auth]]."),
                    ),
                ):
                    exit_code = main(["query", "how do I auth?", "--file-back"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 0
            assert (kb / "qa" / "how-do-i-auth.md").exists()
            index = (kb / "repo.md").read_text(encoding="utf-8")
            assert "[[qa/how-do-i-auth]]" in index

    def test_query_cli_json_answer(self, capsys: pytest.CaptureFixture[str]) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            (kb / "concepts").mkdir()
            (kb / "concepts" / "auth.md").write_text("# Auth")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch(
                        "claude_agent_sdk.query",
                        _fake_sdk_query("Use [[concepts/auth]]."),
                    ),
                ):
                    exit_code = main(["query", "how do I auth?", "--json"])
            finally:
                os.chdir(old_cwd)

            captured = capsys.readouterr()
            payload = json.loads(captured.out)
            assert exit_code == 0
            assert "[[concepts/auth]]" in payload["answer"]
            assert "concepts/auth" in payload["citations"]

    def test_query_cli_json_file_back_writes_article(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            (kb / "concepts").mkdir()
            (kb / "concepts" / "auth.md").write_text("# Auth")
            (kb / "log.md").write_text("# Build Log")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch(
                        "claude_agent_sdk.query",
                        _fake_sdk_query("Use [[concepts/auth]]."),
                    ),
                ):
                    exit_code = main(
                        ["query", "how do I auth?", "--json", "--file-back"]
                    )
            finally:
                os.chdir(old_cwd)

            captured = capsys.readouterr()
            payload = json.loads(captured.out)
            assert exit_code == 0
            assert "Use [[concepts/auth]]" in payload["answer"]
            assert (kb / "qa" / "how-do-i-auth.md").exists()
            assert "Answer filed to" not in captured.out

    def test_query_cli_sdk_missing_exits_two(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Missing claude_agent_sdk is a usage/SDK error (exit 2)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(json.dumps({"repo_name": "repo"}))
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            (kb / "concepts").mkdir()
            (kb / "concepts" / "auth.md").write_text("# Auth")

            old_cwd = os.getcwd()
            original_import = builtins.__import__

            def fake_import(name: str, *args: object, **kwargs: object) -> object:
                if name == "claude_agent_sdk":
                    raise ImportError("No module named 'claude_agent_sdk'")
                return original_import(name, *args, **kwargs)

            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch("builtins.__import__", fake_import),
                ):
                    exit_code = main(["query", "how do I auth?"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 2
            assert "LLM query unavailable" in capsys.readouterr().err
