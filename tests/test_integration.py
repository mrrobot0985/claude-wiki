"""End-to-end integration test for the claude-wiki CLI workflow.

The command implementations for `compile`, `query`, and `lint` are injected at
runtime to verify CLI dispatch and the full repo lifecycle. Once the real
command modules exist under `src/claude_wiki/commands/`, this test can be
updated to use them directly.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any, Callable

import pytest

from claude_wiki.cli import main as kb_main

_Handler = Callable[[Any], int]


def _inject_fake_commands(monkeypatch: pytest.MonkeyPatch) -> None:
    """Register placeholder command modules for compile, query, and lint."""

    def make_module(name: str, register: Callable[..., None]) -> types.ModuleType:
        mod = types.ModuleType(name)
        mod.register = register  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, name, mod)
        return mod

    def register_compile(subparsers: Any, handlers: dict[str, _Handler]) -> None:
        parser = subparsers.add_parser("compile", help="Compile daily logs into the KB")
        parser.add_argument("--all", action="store_true")
        parser.add_argument("--dry-run", action="store_true")

        def handle(args: Any) -> int:
            from claude_wiki.config import ConfigManager

            repo = ConfigManager().find_repo_root(Path.cwd())
            config = ConfigManager().load(repo)
            daily_dir = repo / config.daily_dir
            kb_dir = repo / config.kb_dir
            kb_dir.mkdir(parents=True, exist_ok=True)

            files = sorted(daily_dir.glob("*.md")) if daily_dir.exists() else []
            for file in files:
                text = file.read_text()
                (kb_dir / "index.md").write_text(text)
                concepts_dir = kb_dir / "concepts"
                concepts_dir.mkdir(parents=True, exist_ok=True)
                (concepts_dir / f"{file.stem}.md").write_text(text)

            print(f"Compiled {len(files)} file(s); KB at {kb_dir}")
            return 0

        handlers["compile"] = handle

    def register_query(subparsers: Any, handlers: dict[str, _Handler]) -> None:
        parser = subparsers.add_parser("query", help="Query the knowledge base")
        parser.add_argument("question", nargs="+")
        parser.add_argument("--file-back", action="store_true")

        def handle(args: Any) -> int:
            from claude_wiki.config import ConfigManager

            repo = ConfigManager().find_repo_root(Path.cwd())
            config = ConfigManager().load(repo)
            index = repo / config.kb_dir / "index.md"
            question = " ".join(args.question)

            if index.exists():
                print(f"Answer to '{question}': {index.read_text()[:200]}")
            else:
                print(f"No knowledge index found for '{question}'.")
            return 0

        handlers["query"] = handle

    def register_lint(subparsers: Any, handlers: dict[str, _Handler]) -> None:
        parser = subparsers.add_parser("lint", help="Run health checks on the KB")
        parser.add_argument("--structural-only", action="store_true")

        def handle(args: Any) -> int:
            from claude_wiki.config import ConfigManager

            repo = ConfigManager().find_repo_root(Path.cwd())
            config = ConfigManager().load(repo)
            errors: list[str] = []

            if not (repo / config.daily_dir).exists():
                errors.append("daily directory missing")
            if not (repo / config.kb_dir / "index.md").exists():
                errors.append("knowledge index missing")

            if errors:
                for error in errors:
                    print(f"lint error: {error}")
                return 1

            print("lint passed")
            return 0

        handlers["lint"] = handle

    make_module("claude_wiki.commands.compile", register_compile)
    make_module("claude_wiki.commands.query", register_query)
    make_module("claude_wiki.commands.lint", register_lint)

    import pkgutil

    original_iter_modules = pkgutil.iter_modules

    def fake_iter_modules(path: Any = None, prefix: str = "") -> Any:
        if prefix == "claude_wiki.commands.":
            return [
                (None, "claude_wiki.commands.compile", False),
                (None, "claude_wiki.commands.query", False),
                (None, "claude_wiki.commands.lint", False),
            ]
        return original_iter_modules(path, prefix)

    monkeypatch.setattr("pkgutil.iter_modules", fake_iter_modules)


class TestKBWorkflow:
    """Full repo lifecycle: init -> compile -> query -> lint."""

    def test_init_compile_query_lint_in_temp_repo(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        repo = tmp_path / "demo-repo"
        repo.mkdir()
        (repo / ".git").mkdir()

        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.chdir(repo)

        _inject_fake_commands(monkeypatch)

        assert kb_main(["init"]) == 0
        assert (repo / ".claude-wiki.lock").exists()
        assert (repo / ".claude" / "settings.local.json").exists()
        assert not (Path.home() / ".claude" / "settings.json").exists()

        daily = repo / "daily"
        daily.mkdir()
        (daily / "2026-06-19.md").write_text(
            "# Integration test\n\nA key idea for the knowledge base."
        )

        assert kb_main(["compile"]) == 0
        assert (repo / "knowledge" / "index.md").exists()
        assert (repo / "knowledge" / "concepts" / "2026-06-19.md").exists()

        assert kb_main(["query", "key idea"]) == 0

        assert kb_main(["lint"]) == 0
