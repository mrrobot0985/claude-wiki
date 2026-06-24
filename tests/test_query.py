"""Tests for kb query command."""

import argparse
import asyncio
import builtins
import json
import os
import sys
import tempfile
import types
from typing import Any

from claude_wiki.errors import WriterError
from collections.abc import AsyncIterator, Callable
from datetime import date
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


def _capturing_fake_sdk_query(
    capture: dict[str, str], answer: str
) -> Callable[..., AsyncIterator[object]]:
    """Capture the prompt passed to the fake SDK and return a canned answer."""

    async def fake_query(*, prompt: str, options: object) -> AsyncIterator[object]:
        capture["prompt"] = prompt

        class Block:
            text = answer

        class Message:
            content = [Block()]

        yield Message()

    return fake_query


def _write_article(
    kb: Path,
    category: str,
    name: str,
    body: str,
    *,
    updated: str | None = None,
    created: str | None = None,
    tags: list[str] | None = None,
) -> Path:
    """Create a KB article with optional YAML frontmatter dates and tags."""
    (kb / category).mkdir(parents=True, exist_ok=True)
    parts = ["---"]
    if tags is not None:
        parts.append("tags: [" + ", ".join(f'"{t}"' for t in tags) + "]")
    if updated is not None:
        parts.append(f"updated: {updated}")
    if created is not None:
        parts.append(f"created: {created}")
    parts.append("---")
    frontmatter = "\n".join(parts) + "\n\n" if parts[1:] else ""
    article = kb / category / f"{name}.md"
    article.write_text(frontmatter + body, encoding="utf-8")
    return article


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
            content, count = _read_kb_content(kb, repo_name="test")
            assert content == ""
            assert count == 0

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

            content, count = _read_kb_content(kb, repo_name="test")
            assert "## INDEX" in content
            assert "## concepts/auth.md" in content
            assert "## connections/auth-and-webhooks.md" in content
            assert count == 2


class TestReadKbContentScope:
    """Unit tests for query scoping helpers."""

    def test_category_filter_single(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "auth", "# Auth")
            _write_article(kb, "connections", "auth-and-webhooks", "# Connection")
            _write_article(kb, "qa", "question", "# Q&A")

            content, count = _read_kb_content(
                kb, repo_name="repo", categories=["concepts"]
            )
            assert count == 1
            assert "## concepts/auth.md" in content
            assert "## connections/auth-and-webhooks.md" not in content
            assert "## qa/question.md" not in content

    def test_category_filter_multiple(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "auth", "# Auth")
            _write_article(kb, "connections", "auth-and-webhooks", "# Connection")
            _write_article(kb, "qa", "question", "# Q&A")

            content, count = _read_kb_content(
                kb, repo_name="repo", categories=["concepts", "qa"]
            )
            assert count == 2
            assert "## concepts/auth.md" in content
            assert "## qa/question.md" in content
            assert "## connections/auth-and-webhooks.md" not in content

    def test_since_filter_uses_updated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "old", "# Old", updated="2026-05-01")
            _write_article(kb, "concepts", "new", "# New", updated="2026-06-15")

            content, count = _read_kb_content(
                kb, repo_name="repo", since=date(2026, 6, 1)
            )
            assert count == 1
            assert "## concepts/new.md" in content
            assert "## concepts/old.md" not in content

    def test_since_filter_falls_back_to_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(
                kb, "concepts", "fallback", "# Fallback", created="2026-06-10"
            )
            _write_article(
                kb,
                "concepts",
                "stale",
                "# Stale",
                created="2026-05-10",
                updated="2026-05-15",
            )

            content, count = _read_kb_content(
                kb, repo_name="repo", since=date(2026, 6, 1)
            )
            assert count == 1
            assert "## concepts/fallback.md" in content
            assert "## concepts/stale.md" not in content

    def test_max_chars_drops_oldest_articles(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "old", "# Old\n\nx", updated="2026-06-01")
            _write_article(kb, "concepts", "new", "# New\n\ny", updated="2026-06-10")

            content, count = _read_kb_content(kb, repo_name="repo", max_chars=100)
            assert count == 1
            assert "## concepts/new.md" in content
            assert "## concepts/old.md" not in content
            assert "## INDEX" in content

    def test_max_chars_keeps_all_when_under_budget(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "a", "# A", updated="2026-06-01")
            _write_article(kb, "concepts", "b", "# B", updated="2026-06-02")

            content, count = _read_kb_content(kb, repo_name="repo", max_chars=10000)
            assert count == 2
            assert "## concepts/a.md" in content
            assert "## concepts/b.md" in content

    def test_tag_filter_single(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "rust", "# Rust", tags=["rust"])
            _write_article(kb, "concepts", "python", "# Python", tags=["python"])

            content, count = _read_kb_content(kb, repo_name="repo", tags={"rust"})
            assert count == 1
            assert "## concepts/rust.md" in content
            assert "## concepts/python.md" not in content

    def test_tag_filter_multiple_is_union(self) -> None:
        """Repeatable --tag matches articles tagged with any given tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "rust", "# Rust", tags=["rust"])
            _write_article(kb, "concepts", "python", "# Python", tags=["python"])
            _write_article(kb, "concepts", "js", "# JS", tags=["js"])

            content, count = _read_kb_content(
                kb, repo_name="repo", tags={"rust", "python"}
            )
            assert count == 2
            assert "## concepts/rust.md" in content
            assert "## concepts/python.md" in content
            assert "## concepts/js.md" not in content

    def test_tag_filter_composes_with_category(self) -> None:
        """Tag and category filters AND together."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "rust", "# Rust", tags=["rust"])
            _write_article(kb, "connections", "rust-web", "# Rust web", tags=["rust"])
            _write_article(kb, "concepts", "python", "# Python", tags=["python"])

            content, count = _read_kb_content(
                kb,
                repo_name="repo",
                categories=["concepts"],
                tags={"rust"},
            )
            assert count == 1
            assert "## concepts/rust.md" in content
            assert "## connections/rust-web.md" not in content
            assert "## concepts/python.md" not in content

    def test_tag_filter_composes_with_since_and_max_chars(self) -> None:
        """Tag filter AND-combines with date and size filters."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(
                kb, "concepts", "old", "# Old\n\nx", tags=["rust"], updated="2026-05-01"
            )
            _write_article(
                kb, "concepts", "new", "# New\n\ny", tags=["rust"], updated="2026-06-15"
            )

            content, count = _read_kb_content(
                kb,
                repo_name="repo",
                tags={"rust"},
                since=date(2026, 6, 1),
                max_chars=100,
            )
            assert count == 1
            assert "## concepts/new.md" in content
            assert "## concepts/old.md" not in content

    def test_triple_backticks_in_article_use_longer_fence(self) -> None:
        """Article content containing ``` is wrapped in a fence longer than that run."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(
                kb,
                "concepts",
                "code",
                "```python\nprint('hello')\n```",
                updated="2026-06-20",
            )
            content, count = _read_kb_content(kb, repo_name="repo")
            assert count == 1
            section_start = content.find("## concepts/code.md")
            assert section_start != -1
            section = content[section_start:]
            # The outer fence must be longer than the three backticks inside the article.
            assert "````markdown" in section
            # The raw triple backticks should still be present inside the fence.
            assert "```python" in section


class TestRunQuery:
    """Tests for the core query logic."""

    def test_run_query_empty_kb(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            fake = _fake_sdk_query("should not be called")
            result = asyncio.run(
                _run_query(
                    kb, "question", file_back=False, repo_name="repo", query_func=fake
                )
            )
            assert "No knowledge base found" in result.answer
            assert result.citations == []

    def test_run_query_empty_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "auth", "# Auth", updated="2025-01-01")

            fake = _fake_sdk_query("should not be called")
            result = asyncio.run(
                _run_query(
                    kb,
                    "question",
                    file_back=False,
                    repo_name="repo",
                    since=date(2026, 1, 1),
                    query_func=fake,
                )
            )
            assert result.answer == "No articles matched the requested scope."
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

    def test_run_query_scopes_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "auth", "# Auth")
            _write_article(kb, "connections", "auth-and-webhooks", "# Connection")

            prompt_capture: dict[str, str] = {}
            fake = _capturing_fake_sdk_query(prompt_capture, "answer")
            asyncio.run(
                _run_query(
                    kb,
                    "question",
                    file_back=False,
                    repo_name="repo",
                    categories=["connections"],
                    query_func=fake,
                )
            )
            assert "## connections/auth-and-webhooks.md" in prompt_capture["prompt"]
            assert "## concepts/auth.md" not in prompt_capture["prompt"]

    def test_run_query_sdk_options_use_dontask_permission_mode(
        self, monkeypatch: Any
    ) -> None:
        """When using the real SDK path, query options set permission_mode to dontAsk."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "auth", "# Auth")

            captured: dict[str, Any] = {}

            async def fake_query(
                *, prompt: str, options: object
            ) -> AsyncIterator[object]:
                captured["options"] = options

                class Block:
                    text = "Use [[concepts/auth]]."

                class Message:
                    content = [Block()]

                yield Message()

            class FakeClaudeAgentOptions:
                def __init__(self, **kwargs: Any) -> None:
                    self.kwargs = kwargs

            fake_module = types.SimpleNamespace(
                query=fake_query,
                ClaudeAgentOptions=FakeClaudeAgentOptions,
            )

            monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_module)
            result = asyncio.run(
                _run_query(kb, "how do I auth?", file_back=False, repo_name="repo")
            )

            assert "[[concepts/auth]]" in result.answer
            assert captured["options"].kwargs.get("permission_mode") == "dontAsk"
            assert captured["options"].kwargs.get("permission_mode") != "acceptEdits"


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

    def test_file_back_symlinked_qa_dir_is_rejected(self) -> None:
        """A symlinked qa/ directory pointing outside the vault must not be written."""
        with tempfile.TemporaryDirectory() as tmpdir:
            outside = Path(tmpdir) / "outside"
            outside.mkdir()
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            os.symlink(outside, kb / "qa")
            (kb / "test.md").write_text("# Index")
            (kb / "log.md").write_text("# Build Log")

            result = QueryResult(answer="Answer", citations=[])
            with pytest.raises(WriterError):
                _file_back(kb, "Question?", result, repo_name="test")

            assert not list(outside.glob("*.md"))


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

    def test_append_log_creates_missing_log(self) -> None:
        """A missing log.md is created and the entry appended."""
        with tempfile.TemporaryDirectory() as tmpdir:
            kb = Path(tmpdir) / "kb"
            kb.mkdir()
            _append_log(kb, "2026-06-19T12:00:00", "question", [], "slug")
            log_file = kb / "log.md"
            assert log_file.exists()
            content = log_file.read_text(encoding="utf-8")
            assert "query | question" in content
            assert "[[qa/slug]]" in content


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
        assert args.category is None
        assert args.since is None
        assert args.max_chars is None

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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )

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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )

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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )

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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
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
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
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

    def test_query_cli_bad_since_exit_two(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with pytest.raises(SystemExit) as exc_info:
                    main(["query", "test", "--since", "not-a-date"])
                assert exc_info.value.code == 2
            finally:
                os.chdir(old_cwd)

    def test_query_cli_empty_scope_exit_one(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            (kb / "connections").mkdir()
            (kb / "connections" / "auth.md").write_text("# Auth")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with patch.dict(
                    "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                ):
                    exit_code = main(["query", "test", "--category", "concepts"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 1
            assert "No articles matched the requested scope." in capsys.readouterr().out

    def test_query_cli_category_filter_prompt(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "auth", "# Auth")
            _write_article(kb, "connections", "auth-and-webhooks", "# Connection")

            prompt_capture: dict[str, str] = {}
            fake = _capturing_fake_sdk_query(prompt_capture, "Use [[concepts/auth]].")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch("claude_agent_sdk.query", fake),
                ):
                    exit_code = main(
                        ["query", "how do I auth?", "--category", "concepts"]
                    )
            finally:
                os.chdir(old_cwd)

            assert exit_code == 0
            assert "## concepts/auth.md" in prompt_capture["prompt"]
            assert "## connections/auth-and-webhooks.md" not in prompt_capture["prompt"]

    def test_query_cli_since_filter_prompt(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "old", "# Old auth", updated="2026-05-01")
            _write_article(kb, "concepts", "new", "# New auth", updated="2026-06-15")

            prompt_capture: dict[str, str] = {}
            fake = _capturing_fake_sdk_query(prompt_capture, "Use [[concepts/new]].")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch("claude_agent_sdk.query", fake),
                ):
                    exit_code = main(
                        ["query", "how do I auth?", "--since", "2026-06-01"]
                    )
            finally:
                os.chdir(old_cwd)

            assert exit_code == 0
            assert "## concepts/new.md" in prompt_capture["prompt"]
            assert "## concepts/old.md" not in prompt_capture["prompt"]

    def test_query_cli_max_chars_prompt(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "old", "# Old\n\nx", updated="2026-06-01")
            _write_article(kb, "concepts", "new", "# New\n\ny", updated="2026-06-10")

            prompt_capture: dict[str, str] = {}
            fake = _capturing_fake_sdk_query(prompt_capture, "Use [[concepts/new]].")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch("claude_agent_sdk.query", fake),
                ):
                    exit_code = main(["query", "how do I auth?", "--max-chars", "100"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 0
            assert "## concepts/new.md" in prompt_capture["prompt"]
            assert "## concepts/old.md" not in prompt_capture["prompt"]
            assert "## INDEX" in prompt_capture["prompt"]

    def test_query_cli_tag_filter_prompt(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--tag restricts the prompt to articles with the requested tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "rust", "# Rust", tags=["rust"])
            _write_article(kb, "concepts", "python", "# Python", tags=["python"])

            prompt_capture: dict[str, str] = {}
            fake = _capturing_fake_sdk_query(prompt_capture, "Use [[concepts/rust]].")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch("claude_agent_sdk.query", fake),
                ):
                    exit_code = main(["query", "how do I auth?", "--tag", "rust"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 0
            assert "## concepts/rust.md" in prompt_capture["prompt"]
            assert "## concepts/python.md" not in prompt_capture["prompt"]

    def test_query_cli_multiple_tags_union(self) -> None:
        """Repeatable --tag includes articles matching any named tag."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "rust", "# Rust", tags=["rust"])
            _write_article(kb, "concepts", "python", "# Python", tags=["python"])
            _write_article(kb, "concepts", "js", "# JS", tags=["js"])

            prompt_capture: dict[str, str] = {}
            fake = _capturing_fake_sdk_query(prompt_capture, "answer")

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with (
                    patch.dict(
                        "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                    ),
                    patch("claude_agent_sdk.query", fake),
                ):
                    exit_code = main(["query", "x", "--tag", "rust", "--tag", "python"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 0
            assert "## concepts/rust.md" in prompt_capture["prompt"]
            assert "## concepts/python.md" in prompt_capture["prompt"]
            assert "## concepts/js.md" not in prompt_capture["prompt"]

    def test_query_cli_empty_scope_with_tag(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """--tag with no matching articles produces the empty-scope message."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            (repo / ".git").mkdir()
            (repo / ".claude-wiki.lock").write_text(
                json.dumps({"layout_version": "2", "repo_name": "repo"})
            )
            kb = repo / "knowledge"
            kb.mkdir()
            (kb / "repo.md").write_text("# Index")
            _write_article(kb, "concepts", "python", "# Python", tags=["python"])

            old_cwd = os.getcwd()
            try:
                os.chdir(repo)
                with patch.dict(
                    "os.environ", {"CLAUDE_WIKI_PROJECT_DIR": str(kb)}, clear=False
                ):
                    exit_code = main(["query", "x", "--tag", "rust"])
            finally:
                os.chdir(old_cwd)

            assert exit_code == 1
            assert "No articles matched the requested scope." in capsys.readouterr().out
