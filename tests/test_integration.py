"""End-to-end integration test for the claude-wiki CLI workflow.

Exercises the real CLI commands with LLM calls mocked so the suite runs
offline and deterministically.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from claude_wiki.cli import main
from claude_wiki.models import QueryResult


class TestKBWorkflow:
    """Full repo lifecycle: init -> compile -> query -> lint."""

    @pytest.fixture
    def _fake_home(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        home.mkdir(exist_ok=True)
        monkeypatch.setenv("HOME", str(home))
        return home

    def _bootstrap_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        repo = tmp_path / "demo-repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        monkeypatch.chdir(repo)
        return repo

    def _fake_compile(
        self,
        log_path: Path,
        repo_root: Path,
        kb_root: Path,
        config: Any,
        **kwargs: Any,
    ) -> float:
        """Simulate LLM compilation by writing realistic KB artifacts."""
        kb_root.mkdir(parents=True, exist_ok=True)
        for sub in ("concepts", "connections", "qa"):
            (kb_root / sub).mkdir(parents=True, exist_ok=True)

        catalog = kb_root / f"{config.repo_name}.md"
        if not catalog.exists():
            catalog.write_text(
                f"# {config.repo_name} Knowledge Base\n\n"
                "| Article | Summary | Compiled From | Updated |\n"
                "|---------|---------|---------------|---------|"
            )

        log_name = log_path.name
        date_stub = log_name.replace(".md", "")

        concept_a = kb_root / "concepts" / "uv-python-toolchain.md"
        concept_a.write_text(
            f"---\n"
            f"title: uv Python Toolchain\n"
            f"aliases: [uv]\n"
            f"tags: [python, tooling]\n"
            f"sources:\n"
            f'  - "daily/{log_name}"\n'
            f"created: {date_stub}\n"
            f"updated: {date_stub}\n"
            f"---\n\n"
            f"# uv Python Toolchain\n\n"
            f"Fast Python package manager written in Rust.\n\n"
            f"## Key Points\n\n"
            f"- Replaces pip + virtualenv + pip-tools\n"
            f"- Lockfile support via `uv.lock`\n\n"
            f"## Related Concepts\n\n"
            f"- [[concepts/project-mode-venv]] – uv project mode\n\n"
            f"## Sources\n\n"
            f"- daily/{log_name} – context\n"
        )

        concept_b = kb_root / "concepts" / "project-mode-venv.md"
        concept_b.write_text(
            f"---\n"
            f"title: Project Mode Venv\n"
            f"tags: [python, uv]\n"
            f"sources:\n"
            f'  - "daily/{log_name}"\n'
            f"created: {date_stub}\n"
            f"updated: {date_stub}\n"
            f"---\n\n"
            f"# Project Mode Venv\n\n"
            f"uv can manage virtualenvs automatically in project mode.\n\n"
            f"## Related Concepts\n\n"
            f"- [[concepts/uv-python-toolchain]] – base tool\n\n"
            f"## Sources\n\n"
            f"- daily/{log_name} – context\n"
        )

        connection = kb_root / "connections" / "uv-and-ci-pipelines.md"
        connection.write_text(
            f"---\n"
            f"title: uv and CI Pipelines\n"
            f"tags: [ci, uv]\n"
            f"sources:\n"
            f'  - "daily/{log_name}"\n'
            f"created: {date_stub}\n"
            f"updated: {date_stub}\n"
            f"---\n\n"
            f"# uv and CI Pipelines\n\n"
            f"Using uv in GitHub Actions cuts setup time dramatically.\n\n"
            f"## Related Concepts\n\n"
            f"- [[concepts/uv-python-toolchain]] – base tool\n"
            f"- [[concepts/project-mode-venv]] – project isolation\n\n"
            f"## Sources\n\n"
            f"- daily/{log_name} – context\n"
        )

        log_md = kb_root / "log.md"
        existing_log = log_md.read_text() if log_md.exists() else ""
        log_md.write_text(
            existing_log + f"\n## [{date_stub}T12:00:00] compile | daily/{log_name}\n"
            f"- Source: daily/{log_name}\n"
            f"- Articles created: [[concepts/uv-python-toolchain]], [[concepts/project-mode-venv]], [[connections/uv-and-ci-pipelines]]\n"
            f"- Articles updated: (none)\n"
        )

        catalog_text = catalog.read_text()
        catalog.write_text(
            catalog_text
            + f"\n| [[concepts/uv-python-toolchain]] | uv overview | daily/{log_name} | {date_stub} |"
            + f"\n| [[concepts/project-mode-venv]] | project mode | daily/{log_name} | {date_stub} |"
            + f"\n| [[connections/uv-and-ci-pipelines]] | ci usage | daily/{log_name} | {date_stub} |"
        )

        return 0.0

    def test_init_compile_query_lint_cycle(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mocker: Any,
        _fake_home: Path,
    ) -> None:
        repo = self._bootstrap_repo(tmp_path, monkeypatch)

        # 1. init
        assert main(["init"]) == 0
        assert (repo / ".claude-wiki.lock").exists()
        lock = json.loads((repo / ".claude-wiki.lock").read_text())
        assert lock["repo_name"] == "demo-repo"

        # 2. seed a daily log
        daily = repo / ".claude" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-06-20.md").write_text(
            "# 2026-06-20\n\n"
            "Discussed uv as a replacement for pip and virtualenv.\n\n"
            "Also set up GitHub Actions with uv for faster CI.\n"
        )

        # 3. compile (LLM mocked)
        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=self._fake_compile,
        )
        assert main(["compile"]) == 0

        kb = repo / ".claude" / "knowledge"
        catalog = kb / "demo-repo.md"
        assert catalog.exists()
        catalog_text = catalog.read_text()
        assert "[[concepts/uv-python-toolchain]]" in catalog_text
        assert "[[connections/uv-and-ci-pipelines]]" in catalog_text

        concept = kb / "concepts" / "uv-python-toolchain.md"
        assert concept.exists()
        assert "uv Python Toolchain" in concept.read_text()

        assert (kb / "concepts" / "project-mode-venv.md").exists()

        connection = kb / "connections" / "uv-and-ci-pipelines.md"
        assert connection.exists()

        log_md = kb / "log.md"
        assert log_md.exists()
        assert "compile | daily/2026-06-20.md" in log_md.read_text()

        state_path = repo / ".claude" / "state" / "state.json"
        state = json.loads(state_path.read_text())
        assert "2026-06-20.md" in state["ingested"]

        # 4. query (LLM mocked via _run_query)
        with patch(
            "claude_wiki.commands.query._run_query",
            return_value=QueryResult(
                answer="uv is a fast Python package manager.",
                citations=["concepts/uv-python-toolchain"],
            ),
        ):
            assert main(["query", "what is uv?"]) == 0
            # file_back is not triggered in this mock path because _run_query
            # is fully replaced; test file_back separately in unit tests.
            # We just verify query exits cleanly.

        # 5. lint — structural only (no LLM)
        assert main(["lint", "--structural-only"]) == 0

    def test_compile_then_lint_finds_no_issues_on_pristine_kb(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mocker: Any,
        _fake_home: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """A freshly compiled synthetic KB passes structural lint cleanly."""
        repo = self._bootstrap_repo(tmp_path, monkeypatch)

        assert main(["init"]) == 0
        daily = repo / ".claude" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-06-20.md").write_text("Learned about uv.")

        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=self._fake_compile,
        )
        assert main(["compile"]) == 0

        exit_code = main(["lint", "--structural-only"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "0 errors" in captured.out

    def test_query_with_file_back_writes_qa_article(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mocker: Any,
        _fake_home: Path,
    ) -> None:
        """query --file-back persists the answer into the knowledge base."""
        repo = self._bootstrap_repo(tmp_path, monkeypatch)

        assert main(["init"]) == 0
        daily = repo / ".claude" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-06-20.md").write_text("Learned about uv.")

        mocker.patch(
            "claude_wiki.commands.compile._compile_one",
            side_effect=self._fake_compile,
        )
        assert main(["compile"]) == 0

        with patch(
            "claude_wiki.commands.query._run_query",
            return_value=QueryResult(
                answer="uv replaces pip and virtualenv.",
                citations=["concepts/uv-python-toolchain"],
            ),
        ):
            assert main(["query", "what replaces pip?", "--file-back"]) == 0

        kb = repo / ".claude" / "knowledge"
        qa_file = kb / "qa" / "what-replaces-pip.md"
        assert qa_file.exists()
        text = qa_file.read_text()
        assert "uv replaces pip and virtualenv." in text
        assert "[[concepts/uv-python-toolchain]]" in text

        log_md = kb / "log.md"
        assert "query | what replaces pip?" in log_md.read_text()
        assert "[[qa/what-replaces-pip]]" in log_md.read_text()
