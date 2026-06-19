"""PreCompact hook handler — extracts conversation context before compaction."""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from claude_wiki.config import ConfigManager

_spawn_flush: Any = None
try:
    from claude_wiki.flush import spawn_flush as _spawn_flush
except ImportError:
    pass

logger = logging.getLogger(__name__)

MAX_TURNS = 30
MAX_CONTEXT_CHARS = 15_000
MIN_TURNS_TO_FLUSH = 5


def _setup_logging(scripts_dir: Path) -> None:
    """Configure file logging under scripts/flush.log."""
    scripts_dir.mkdir(parents=True, exist_ok=True)
    log_file = scripts_dir / "flush.log"

    logger.setLevel(logging.INFO)
    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    handler = logging.FileHandler(log_file)
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s [pre-compact] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)


def _extract_context(transcript_path: Path) -> tuple[str, int]:
    """Read a JSONL transcript and return the recent conversation context."""
    turns: list[str] = []

    with transcript_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg = entry.get("message", {})
            if isinstance(msg, dict):
                role = msg.get("role", "")
                content = msg.get("content", "")
            else:
                role = entry.get("role", "")
                content = entry.get("content", "")

            if role not in ("user", "assistant"):
                continue

            if isinstance(content, list):
                text_parts: list[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_parts.append(block.get("text", ""))
                    elif isinstance(block, str):
                        text_parts.append(block)
                content = "\n".join(text_parts)

            if isinstance(content, str) and content.strip():
                label = "User" if role == "user" else "Assistant"
                turns.append(f"**{label}:** {content.strip()}\n")

    recent = turns[-MAX_TURNS:]
    context = "\n".join(recent)

    if len(context) > MAX_CONTEXT_CHARS:
        context = context[-MAX_CONTEXT_CHARS:]
        boundary = context.find("\n**")
        if boundary > 0:
            context = context[boundary + 1 :]

    return context, len(recent)


def _read_hook_input() -> dict[str, Any]:
    """Parse JSON hook input from stdin, tolerating lightly-escaped JSON."""
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    try:
        return cast(dict[str, Any], json.loads(raw))
    except json.JSONDecodeError:
        fixed = re.sub(r"(?<!\\)\\(?!\"\\)", r"\\\\", raw)
        return cast(dict[str, Any], json.loads(fixed))


def handler(_args: list[str]) -> int:
    """Handle the PreCompact hook event."""
    # Recursion guard: flush processes must not re-trigger this hook.
    if os.environ.get("CLAUDE_INVOKED_BY"):
        return 0

    try:
        repo_root = ConfigManager().find_repo_root(Path.cwd())
    except Exception as exc:
        logging.error("Failed to locate repo root: %s", exc)
        return 1

    scripts_dir = repo_root / "scripts"
    _setup_logging(scripts_dir)

    try:
        hook_input = _read_hook_input()
    except (json.JSONDecodeError, ValueError, EOFError) as exc:
        logger.error("Failed to parse stdin: %s", exc)
        return 1

    session_id = hook_input.get("session_id", "unknown")
    transcript_path_str = hook_input.get("transcript_path", "")

    logger.info("PreCompact fired: session=%s", session_id)

    if not transcript_path_str or not isinstance(transcript_path_str, str):
        logger.info("SKIP: no transcript path")
        return 0

    transcript_path = Path(transcript_path_str)
    if not transcript_path.exists():
        logger.info("SKIP: transcript missing: %s", transcript_path_str)
        return 0

    try:
        context, turn_count = _extract_context(transcript_path)
    except Exception as exc:
        logger.error("Context extraction failed: %s", exc)
        return 1

    if not context.strip():
        logger.info("SKIP: empty context")
        return 0

    if turn_count < MIN_TURNS_TO_FLUSH:
        logger.info("SKIP: only %d turns (min %d)", turn_count, MIN_TURNS_TO_FLUSH)
        return 0

    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = scripts_dir / f"flush-context-{session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")

    if _spawn_flush is None:
        logger.error("Shared flush logic unavailable: claude_wiki.flush is not installed")
        return 1

    try:
        _spawn_flush(context_file, session_id, repo_root)
    except Exception as exc:
        logger.error("Failed to spawn flush: %s", exc)
        return 1

    logger.info(
        "Spawned flush for session %s (%d turns, %d chars)",
        session_id,
        turn_count,
        len(context),
    )
    return 0


def register(handlers: dict[str, Any]) -> None:
    """Register the PreCompact handler for auto-discovery."""
    handlers["PreCompact"] = handler
