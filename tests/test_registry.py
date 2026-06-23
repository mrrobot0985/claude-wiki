"""Tests for the `claude-wiki registry` command group."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from claude_wiki.cli import main
from claude_wiki.commands.registry import (
    _handle_registry,
    _parse_repo_spec,
)
from claude_wiki.global_index import GlobalIndexManager


def _make_repo(tmpdir: Path, name: str, *, kb_mode: str = "project") -> Path:
    """Create a fake repo root with a valid .claude-wiki.lock."""
    repo = tmpdir / name
    repo.mkdir()
    lock = {
        "layout_version": "2",
        "repo_name": name,
        "repo_owner": "local",
        "kb_dir": kb_mode,
        "daily_dir": "daily",
    }
    (repo / ".claude-wiki.lock").write_text(json.dumps(lock))
    return repo


def _register_repo(
    mgr: GlobalIndexManager,
    owner: str,
    name: str,
    kb_root: Path,
    repo_root: Path | None = None,
    *,
    articles: int = 0,
    last_compiled: str | None = None,
) -> None:
    kwargs: dict[str, object] = {}
    if articles:
        kwargs["articles"] = articles
    if last_compiled:
        kwargs["last_compiled"] = last_compiled
    if repo_root is not None:
        kwargs["repo_root"] = repo_root
    mgr.register(name, owner, kb_root, **kwargs)


class TestParseRepoSpec:
    """Unit tests for the owner/repo argument parser."""

    def test_valid_spec(self) -> None:
        assert _parse_repo_spec("owner/repo") == ("owner", "repo")

    def test_missing_owner(self) -> None:
        assert _parse_repo_spec("/repo") is None

    def test_missing_name(self) -> None:
        assert _parse_repo_spec("owner/") is None

    def test_too_many_slashes(self) -> None:
        assert _parse_repo_spec("owner/repo/extra") is None

    def test_no_slash(self) -> None:
        assert _parse_repo_spec("repo") is None


class TestRegistryList:
    """Tests for `claude-wiki registry list`."""

    def test_list_empty_registry(self, capsys) -> None:
        args = argparse.Namespace(registry_command="list")
        assert _handle_registry(args) == 0
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_list_prints_sorted_entries(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo_a = _make_repo(tmp_path, "alpha")
        repo_z = _make_repo(tmp_path, "zebra")
        _register_repo(mgr, "beta", "zebra", tmp_path / "kb1", repo_z, articles=3)
        _register_repo(mgr, "beta", "alpha", tmp_path / "kb2", repo_a, articles=7)

        args = argparse.Namespace(registry_command="list")
        assert _handle_registry(args) == 0
        captured = capsys.readouterr()
        out = captured.out

        # Sorted by owner then name: beta/alpha before beta/zebra.
        alpha_pos = out.find("beta/alpha")
        zebra_pos = out.find("beta/zebra")
        assert 0 <= alpha_pos < zebra_pos
        assert "project-local KB" in out
        assert "kb_root:" in out
        assert "repo_root:" in out
        assert "articles: 7" in out
        assert "articles: 3" in out

    def test_list_user_mode_label(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "user-repo", kb_mode="user")
        _register_repo(mgr, "local", "user-repo", tmp_path / "kb", repo)

        args = argparse.Namespace(registry_command="list")
        assert _handle_registry(args) == 0
        assert "user KB" in capsys.readouterr().out

    def test_list_legacy_entry_without_repo_root(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        _register_repo(mgr, "legacy", "owner", tmp_path / "kb")

        args = argparse.Namespace(registry_command="list")
        assert _handle_registry(args) == 0
        out = capsys.readouterr().out
        assert "legacy/owner" in out
        assert "repo_root: n/a" in out


class TestRegistryShow:
    """Tests for `claude-wiki registry show <owner/repo>`."""

    def test_show_existing_entry(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "shown")
        _register_repo(
            mgr,
            "owner",
            "shown",
            tmp_path / "kb",
            repo,
            articles=4,
            last_compiled="2026-06-19",
        )

        args = argparse.Namespace(registry_command="show", repo="owner/shown")
        assert _handle_registry(args) == 0
        out = capsys.readouterr().out
        assert "owner/shown" in out
        assert "articles: 4" in out
        assert "2026-06-19" in out

    def test_show_missing_entry_exits_one(self, capsys, tmp_path) -> None:
        args = argparse.Namespace(registry_command="show", repo="owner/missing")
        assert _handle_registry(args) == 1
        captured = capsys.readouterr()
        assert "not found" in captured.err

    def test_show_invalid_spec_exits_one(self, capsys) -> None:
        args = argparse.Namespace(registry_command="show", repo="not-a-spec")
        assert _handle_registry(args) == 1
        assert "Expected owner/repo" in capsys.readouterr().err


class TestRegistryRemove:
    """Tests for `claude-wiki registry remove <owner/repo> [--yes]`."""

    def test_remove_with_yes_deletes_entry_and_regenerates_core(self, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "removed")
        _register_repo(mgr, "owner", "removed", tmp_path / "kb", repo)
        assert len(mgr.list_entries()) == 1

        args = argparse.Namespace(
            registry_command="remove", repo="owner/removed", yes=True
        )
        assert _handle_registry(args) == 0

        assert len(mgr.list_entries()) == 0
        assert (mgr.base_dir / "core.md").exists()

    def test_remove_without_yes_non_tty_aborts(self, tmp_path, monkeypatch) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "kept")
        _register_repo(mgr, "owner", "kept", tmp_path / "kb", repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: False)

        args = argparse.Namespace(
            registry_command="remove", repo="owner/kept", yes=False
        )
        assert _handle_registry(args) == 1
        assert len(mgr.list_entries()) == 1

    def test_remove_tty_decline_aborts(self, tmp_path, monkeypatch) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "kept")
        _register_repo(mgr, "owner", "kept", tmp_path / "kb", repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "n")

        args = argparse.Namespace(
            registry_command="remove", repo="owner/kept", yes=False
        )
        assert _handle_registry(args) == 1
        assert len(mgr.list_entries()) == 1

    def test_remove_tty_confirm_removes(self, tmp_path, monkeypatch) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "gone")
        _register_repo(mgr, "owner", "gone", tmp_path / "kb", repo)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)
        monkeypatch.setattr("builtins.input", lambda _: "y")

        args = argparse.Namespace(
            registry_command="remove", repo="owner/gone", yes=False
        )
        assert _handle_registry(args) == 0
        assert len(mgr.list_entries()) == 0

    def test_remove_missing_entry_exits_one(self, capsys) -> None:
        args = argparse.Namespace(
            registry_command="remove", repo="owner/missing", yes=True
        )
        assert _handle_registry(args) == 1
        assert "not found" in capsys.readouterr().err


class TestRegistryClean:
    """Tests for `claude-wiki registry clean`."""

    def test_clean_evicts_stale_entries(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        alive_repo = _make_repo(tmp_path, "alive")
        dead_repo = _make_repo(tmp_path, "dead")
        _register_repo(mgr, "owner", "alive", tmp_path / "kb1", alive_repo)
        _register_repo(mgr, "owner", "dead", tmp_path / "kb2", dead_repo)

        # Remove the dead repo root and its lock.
        (dead_repo / ".claude-wiki.lock").unlink()
        dead_repo.rmdir()

        args = argparse.Namespace(registry_command="clean")
        assert _handle_registry(args) == 0
        out = capsys.readouterr().out
        assert "owner/dead" in out
        entries = mgr.list_entries()
        assert len(entries) == 1
        assert entries[0].repo_name == "alive"

    def test_clean_reports_no_stale_entries(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "alive")
        _register_repo(mgr, "owner", "alive", tmp_path / "kb", repo)

        args = argparse.Namespace(registry_command="clean")
        assert _handle_registry(args) == 0
        assert "No stale" in capsys.readouterr().out


class TestRegistryCliIntegration:
    """End-to-end tests through `claude_wiki.cli.main`."""

    def test_main_registry_list(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "integ")
        _register_repo(mgr, "owner", "integ", tmp_path / "kb", repo)

        exit_code = main(["registry", "list"])
        assert exit_code == 0
        assert "owner/integ" in capsys.readouterr().out

    def test_main_registry_show(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "integ")
        _register_repo(mgr, "owner", "integ", tmp_path / "kb", repo)

        assert main(["registry", "show", "owner/integ"]) == 0
        assert "owner/integ" in capsys.readouterr().out

    def test_main_registry_show_missing(self, capsys) -> None:
        assert main(["registry", "show", "owner/missing"]) == 1
        assert "not found" in capsys.readouterr().err

    def test_main_registry_remove_yes(self, tmp_path) -> None:
        mgr = GlobalIndexManager()
        repo = _make_repo(tmp_path, "integ")
        _register_repo(mgr, "owner", "integ", tmp_path / "kb", repo)

        assert main(["registry", "remove", "owner/integ", "--yes"]) == 0
        assert len(mgr.list_entries()) == 0

    def test_main_registry_clean(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        alive_repo = _make_repo(tmp_path, "alive")
        dead_repo = _make_repo(tmp_path, "dead")
        _register_repo(mgr, "owner", "alive", tmp_path / "kb1", alive_repo)
        _register_repo(mgr, "owner", "dead", tmp_path / "kb2", dead_repo)
        (dead_repo / ".claude-wiki.lock").unlink()
        dead_repo.rmdir()

        assert main(["registry", "clean"]) == 0
        assert "owner/dead" in capsys.readouterr().out


class TestRegistryListLegacyEntry:
    """Regression guard for legacy entries without a repo_root."""

    def test_legacy_entry_unknown_mode(self, capsys, tmp_path) -> None:
        mgr = GlobalIndexManager()
        _register_repo(mgr, "legacy", "owner", tmp_path / "kb")

        args = argparse.Namespace(registry_command="list")
        assert _handle_registry(args) == 0
        out = capsys.readouterr().out
        assert "(unknown)" in out
