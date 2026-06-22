"""`claude-wiki status` — diagnose repository health."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None  # type: ignore[assignment]

from claude_wiki.catalog_utils import resolve_catalog
from claude_wiki.config import ConfigManager
from claude_wiki.errors import ConfigError, RepoNotFoundError
from claude_wiki.global_index import GlobalIndexManager
from claude_wiki.hook_detect import (
    global_claude_settings_path,
    settings_has_claude_wiki_hooks,
)
from claude_wiki.models import ProjectConfig


_StatusIcon = {"ok": "✓", "warn": "⚠", "err": "✗"}


def _check_lock(repo_root: Path) -> tuple[str, str, int]:
    marker = repo_root / ".claude-wiki.lock"
    if not marker.exists():
        return (
            "Lock file",
            f"{_StatusIcon['err']} .claude-wiki.lock missing — run `claude-wiki init`",
            1,
        )
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("not a JSON object")
    except (OSError, ValueError) as exc:
        return (
            "Lock file",
            f"{_StatusIcon['err']} .claude-wiki.lock corrupt: {exc}",
            1,
        )
    return (
        "Lock file",
        f"{_StatusIcon['ok']} .claude-wiki.lock present and valid",
        0,
    )


def _check_config(repo_root: Path) -> tuple[str, str, int]:
    try:
        config = ConfigManager().load(repo_root)
    except ConfigError as exc:
        return ("Config", f"{_StatusIcon['err']} {exc}", 1)
    return (
        "Config",
        f"{_StatusIcon['ok']} repo_name={config.repo_name}, owner={config.repo_owner}",
        0,
    )


def _check_daily(repo_root: Path, config: ProjectConfig) -> tuple[str, str, int]:
    daily = (
        config.daily_dir
        if config.daily_dir.is_absolute()
        else (repo_root / config.daily_dir).resolve(strict=False)
    )
    if not daily.exists():
        return (
            "Daily logs",
            f"{_StatusIcon['warn']} daily dir missing ({daily})",
            0,
        )
    files = list(daily.glob("*.md"))
    if not files:
        return (
            "Daily logs",
            f"{_StatusIcon['warn']} 0 files in {daily}",
            0,
        )
    return (
        "Daily logs",
        f"{_StatusIcon['ok']} {len(files)} file(s) in {daily}",
        0,
    )


def _check_kb(
    repo_root: Path, config: ProjectConfig
) -> tuple[list[tuple[str, str, int]], int]:
    kb_root = ConfigManager().get_kb_root(repo_root, config)
    lines: list[tuple[str, str, int]] = []
    errs = 0

    if not kb_root.exists():
        lines.append(
            ("Knowledge base", f"{_StatusIcon['warn']} KB dir missing ({kb_root})", 0)
        )
        return lines, errs

    catalog = resolve_catalog(kb_root, config.repo_name)
    if catalog.exists():
        lines.append(
            ("Knowledge base", f"{_StatusIcon['ok']} {catalog.name} present", 0)
        )
    else:
        lines.append(
            ("Knowledge base", f"{_StatusIcon['err']} {catalog.name} missing", 1)
        )
        errs += 1

    counts: list[str] = []
    for subdir_name in ("concepts", "connections", "qa"):
        subdir = kb_root / subdir_name
        count = len(list(subdir.glob("*.md"))) if subdir.exists() else 0
        if count:
            counts.append(f"{count} {subdir_name}")
    if counts:
        lines.append(("Knowledge base", f"{_StatusIcon['ok']} {', '.join(counts)}", 0))
    else:
        lines.append(
            ("Knowledge base", f"{_StatusIcon['warn']} 0 articles compiled", 0)
        )

    return lines, errs


def _check_state(repo_root: Path, config: ProjectConfig) -> tuple[str, str, int]:
    state_dir = ConfigManager().get_machine_state_dir(repo_root, config)
    state_path = state_dir / "state.json"
    if not state_path.exists():
        return (
            "State",
            f"{_StatusIcon['warn']} state.json missing — nothing compiled yet",
            0,
        )
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        ingested = len(data.get("ingested", {}))
        total_cost = data.get("total_cost", 0.0)
        return (
            "State",
            f"{_StatusIcon['ok']} {ingested} ingested, ${total_cost:.4f} total cost",
            0,
        )
    except (OSError, ValueError) as exc:
        return (
            "State",
            f"{_StatusIcon['warn']} state.json unreadable: {exc}",
            0,
        )


def _check_hooks(repo_root: Path) -> tuple[str, str, int]:
    local = repo_root / ".claude" / "settings.local.json"
    global_ = global_claude_settings_path()
    required_events = {"SessionStart", "SessionEnd", "PreCompact"}

    local_has_ours = settings_has_claude_wiki_hooks(local)
    global_has_ours = settings_has_claude_wiki_hooks(global_)

    if local_has_ours and global_has_ours:
        return (
            "Hooks",
            f"{_StatusIcon['err']} claude-wiki hooks detected in both repo-local and global settings",
            1,
        )

    for path, label in ((local, "repo-local"), (global_, "global")):
        if not path.exists():
            continue
        try:
            settings = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        hooks = settings.get("hooks", {})
        present = {evt for evt in required_events if evt in hooks and hooks[evt]}
        if present == required_events:
            return (
                "Hooks",
                f"{_StatusIcon['ok']} {', '.join(sorted(required_events))} in {label} settings",
                0,
            )
        if present:
            missing = required_events - present
            return (
                "Hooks",
                f"{_StatusIcon['warn']} missing {', '.join(sorted(missing))} in {label} settings",
                0,
            )

    return (
        "Hooks",
        f"{_StatusIcon['err']} no hooks found — run `claude-wiki init`",
        1,
    )


def _check_registry(config: ProjectConfig) -> tuple[str, str, int]:
    try:
        entries = GlobalIndexManager()._load_registry()
    except Exception:  # pragma: no cover
        return ("Registry", f"{_StatusIcon['warn']} unable to read registry", 0)

    for entry in entries:
        if (
            entry.repo_name == config.repo_name
            and entry.repo_owner == config.repo_owner
        ):
            compiled = entry.last_compiled or "never"
            return (
                "Registry",
                f"{_StatusIcon['ok']} {entry.articles} articles, last compiled {compiled}",
                0,
            )

    return (
        "Registry",
        f"{_StatusIcon['warn']} not registered — run `claude-wiki compile`",
        0,
    )


def _check_concurrency() -> tuple[str, str, int]:
    if sys.platform == "win32" or fcntl is None:
        return (
            "Concurrency",
            f"{_StatusIcon['warn']} write serialization not available on this platform (concurrent writes may race)",
            0,
        )
    return (
        "Concurrency",
        f"{_StatusIcon['ok']} write serialization active (fcntl advisory locks)",
        0,
    )


def _row_status(message: str, errors: int) -> str:
    """Map a human row to a machine status label."""
    if errors > 0:
        return "error"
    if message.startswith(_StatusIcon["warn"]):
        return "warning"
    return "ok"


def _strip_icon(message: str) -> str:
    """Remove the leading status icon and one trailing space, if present."""
    for icon in _StatusIcon.values():
        if message.startswith(icon):
            return message[len(icon) :].lstrip(" ")
    return message


def _print_status_json(repo_name: str, rows: list[tuple[str, str, int]]) -> None:
    """Emit the diagnostic rows as machine-readable JSON."""
    total_errors = sum(err for _label, _msg, err in rows)
    checks: list[dict[str, Any]] = []
    for label, msg, err in rows:
        checks.append(
            {
                "name": label,
                "status": _row_status(msg, err),
                "message": _strip_icon(msg),
                "errors": err,
            }
        )
    payload = {
        "repo": repo_name,
        "total_errors": total_errors,
        "checks": checks,
    }
    print(json.dumps(payload, indent=2))


def _handle_status(args: argparse.Namespace) -> int:
    """Print diagnostic report for the current repo."""
    detector = ConfigManager()
    start = args.path if args.path else Path.cwd()
    try:
        repo_root = detector.find_repo_root(start)
    except RepoNotFoundError:
        if args.json:
            print(json.dumps({"error": "Not in a git repository"}))
        else:
            print("Error: Not in a git repository.", file=sys.stderr)
        return 1

    total_errors = 0
    rows: list[tuple[str, str, int]] = []

    # Lock
    label, msg, err = _check_lock(repo_root)
    rows.append((label, msg, err))
    total_errors += err

    # If lock is missing or corrupt, stop early — downstream checks need config.
    lock_ok = not err

    if lock_ok:
        label, msg, err = _check_config(repo_root)
        rows.append((label, msg, err))
        total_errors += err
        config_ok = not err
    else:
        config_ok = False

    if config_ok:
        config = detector.load(repo_root)
        label, msg, err = _check_daily(repo_root, config)
        rows.append((label, msg, err))
        total_errors += err

        kb_lines, kb_errs = _check_kb(repo_root, config)
        total_errors += kb_errs
        rows.extend(kb_lines)

        label, msg, err = _check_state(repo_root, config)
        rows.append((label, msg, err))
        total_errors += err

        label, msg, err = _check_hooks(repo_root)
        rows.append((label, msg, err))
        total_errors += err

        label, msg, err = _check_registry(config)
        rows.append((label, msg, err))
        total_errors += err
    else:
        rows.append(
            ("Daily logs", f"{_StatusIcon['warn']} skipped — config unavailable", 0)
        )
        rows.append(
            ("Knowledge base", f"{_StatusIcon['warn']} skipped — config unavailable", 0)
        )
        rows.append(("State", f"{_StatusIcon['warn']} skipped — config unavailable", 0))
        rows.append(("Hooks", f"{_StatusIcon['warn']} skipped — config unavailable", 0))
        rows.append(
            ("Registry", f"{_StatusIcon['warn']} skipped — config unavailable", 0)
        )

    label, msg, err = _check_concurrency()
    rows.append((label, msg, err))
    total_errors += err

    if args.json:
        _print_status_json(repo_root.name, rows)
        return 1 if total_errors else 0

    # Human output
    print(f"claude-wiki status for {repo_root.name}\n")

    # Pretty-print aligned rows
    labels = [r[0] for r in rows]
    max_len = max(len(label) for label in labels) if labels else 0
    for label, msg, _err in rows:
        pad = " " * (max_len - len(label))
        print(f"{label}{pad}  {msg}")

    if total_errors:
        print(f"\n{total_errors} error(s) found.")
        return 1
    print("\nAll checks passed.")
    return 0


def register(
    subparsers: argparse._SubParsersAction,  # type: ignore[type-arg]
    handlers: dict[str, Callable[[argparse.Namespace], int]],
) -> None:
    parser = subparsers.add_parser("status", help="Diagnose repository health")
    parser.add_argument(
        "--path",
        type=Path,
        help="Repo root (default: auto-detect from current directory)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON instead of human text",
    )
    handlers["status"] = _handle_status
