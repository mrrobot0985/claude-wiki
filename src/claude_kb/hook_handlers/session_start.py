"""SessionStart hook handler - injects KB context into Claude Code sessions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from claude_kb.config import ConfigManager
from claude_kb.models import ProjectConfig

MAX_CONTEXT_CHARS = 20_000
MAX_LOG_LINES = 30


def _find_repo_root(start: Path | None = None) -> Path | None:
    """Walk upward from start to locate .git or .claude-wiki.json."""
    manager = ConfigManager()
    try:
        return manager.find_repo_root(start or Path.cwd())
    except Exception:
        return None


def _load_config(repo_root: Path | None) -> ProjectConfig | None:
    """Load .claude-wiki.json, or return None if not in a repo."""
    if repo_root is None:
        return None
    try:
        return ConfigManager().load(repo_root)
    except Exception:
        return None


def _get_kb_index(kb_root: Path) -> str:
    """Read knowledge/index.md if it exists."""
    index_file = kb_root / "index.md"
    if index_file.exists():
        return index_file.read_text(encoding="utf-8")
    return "(empty - no articles compiled yet)"


def _get_recent_daily_log(daily_dir: Path) -> str:
    """Read the most recent daily log (today or yesterday), capped to last 30 lines."""
    today = datetime.now(timezone.utc).astimezone()
    for offset in range(2):
        date = today - timedelta(days=offset)
        log_path = daily_dir / f"{date.strftime('%Y-%m-%d')}.md"
        if log_path.exists():
            lines = log_path.read_text(encoding="utf-8").splitlines()
            recent = lines[-MAX_LOG_LINES:] if len(lines) > MAX_LOG_LINES else lines
            return "\n".join(recent)
    return "(no recent daily log)"


def _build_context(repo_root: Path | None, config: ProjectConfig | None) -> str:
    """Assemble the context injected into the conversation."""
    parts = []

    today = datetime.now(timezone.utc).astimezone()
    parts.append(f"## Today\n{today.strftime('%A, %B %d, %Y')}")

    if repo_root is not None and config is not None:
        try:
            kb_root = ConfigManager().get_kb_root(config)
            index = _get_kb_index(kb_root)
            parts.append(f"## Knowledge Base Index\n\n{index}")
        except Exception:
            parts.append(
                "## Knowledge Base Index\n\n(empty - no articles compiled yet)"
            )

        try:
            daily_dir = repo_root / config.daily_dir
            recent_log = _get_recent_daily_log(daily_dir)
            parts.append(f"## Recent Daily Log\n\n{recent_log}")
        except Exception:
            parts.append("## Recent Daily Log\n\n(no recent daily log)")
    else:
        parts.append("## Knowledge Base Index\n\n(empty - no articles compiled yet)")
        parts.append("## Recent Daily Log\n\n(no recent daily log)")

    context = "\n\n---\n\n".join(parts)
    if len(context) > MAX_CONTEXT_CHARS:
        trailer = "\n\n...(truncated)"
        context = context[: MAX_CONTEXT_CHARS - len(trailer)] + trailer

    return context


def _session_start(argv: list[str]) -> int:
    """Handle the SessionStart hook event."""
    repo_root = _find_repo_root()
    config = _load_config(repo_root)
    context = _build_context(repo_root, config)

    output = {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }
    print(json.dumps(output))
    return 0


def register(handlers: dict[str, object]) -> None:
    """Register the SessionStart handler for auto-discovery."""
    handlers["SessionStart"] = _session_start
