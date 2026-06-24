"""SessionEnd hook handler — fast local I/O, then spawn background flush."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path
from typing import Any

from claude_wiki import flush
from claude_wiki.config import ConfigManager
from claude_wiki.errors import ClaudeKBError
from claude_wiki.logging_setup import configure_stderr_logging

logger = logging.getLogger(__name__)


def _handle_session_end(argv: list[str]) -> int:
    """Handle a Claude Code SessionEnd hook invocation.

    Reads JSON from stdin, extracts the last conversation turns from the
    transcript, and spawns ``claude_wiki.flush`` in the background to do the
    LLM work.
    """
    configure_stderr_logging()

    # Recursion guard: if a nested Claude invocation triggered by the Agent SDK
    # somehow fires this hook, exit immediately without doing any work.
    if os.environ.get("CLAUDE_INVOKED_BY"):
        return 0

    raw = sys.stdin.read()
    try:
        hook_input: dict[str, Any] = flush.read_hook_input(raw)
    except (json.JSONDecodeError, ValueError) as e:
        _try_log_error(f"Failed to parse stdin: {e}")
        return 0

    session_id = hook_input.get("session_id", "unknown")
    transcript_path_str = hook_input.get("transcript_path", "")

    if not isinstance(transcript_path_str, str) or not transcript_path_str:
        _try_log("SessionEnd fired: session={session_id} SKIP: no transcript path")
        return 0

    try:
        manager = ConfigManager()
        repo_root = manager.find_repo_root(Path.cwd())
        config = manager.load(repo_root)
    except ClaudeKBError as e:
        _try_log_error(f"Could not load repo config: {e}")
        return 0

    logs_dir = flush.get_logs_dir(config, repo_root)
    log_path = logs_dir / "flush.log"
    flush.configure_logging(log_path)

    source = hook_input.get("source", "unknown")
    logger.info("SessionEnd fired: session=%s source=%s", session_id, source)

    transcript_path = Path(transcript_path_str)
    try:
        flush.validate_transcript_path(transcript_path, repo_root)
    except ValueError as e:
        logger.error("Rejected transcript path: %s", flush._sanitize_for_log(e))
        return 0

    if not transcript_path.exists():
        logger.info("SKIP: transcript missing: %s", transcript_path_str)
        return 0

    try:
        context, turn_count = flush.extract_conversation_context(transcript_path)
    except Exception as e:
        logger.error("Context extraction failed: %s", flush._sanitize_for_log(e))
        return 0

    if not context.strip():
        logger.info("SKIP: empty context")
        return 0

    if turn_count < flush.DEFAULT_MIN_TURNS_TO_FLUSH:
        logger.info(
            "SKIP: only %d turns (min %d)", turn_count, flush.DEFAULT_MIN_TURNS_TO_FLUSH
        )
        return 0

    cache_dir = manager.get_cache_dir(repo_root, config)
    context_file = flush.write_context_file(
        cache_dir, session_id, context, prefix="session-flush"
    )

    try:
        proc = flush.spawn_flush(context_file, session_id, repo_root)
        logger.info(
            "Spawned flush.py for session %s (%d turns, %d chars) pid=%s",
            session_id,
            turn_count,
            len(context),
            proc.pid,
        )
    except Exception as e:
        logger.error("Failed to spawn flush.py: %s", flush._sanitize_for_log(e))

    return 0


def _try_log(message: str) -> None:
    """Best-effort log when full config is not yet available."""
    try:
        manager = ConfigManager()
        repo_root = manager.find_repo_root(Path.cwd())
        config = manager.load(repo_root)
        logs_dir = flush.get_logs_dir(config, repo_root)
        flush.configure_logging(logs_dir / "flush.log")
        logger.info(message)
    except Exception as exc:
        logger.warning(
            "Best-effort logging unavailable: %s", flush._sanitize_for_log(exc)
        )


def _try_log_error(message: str) -> None:
    """Best-effort error log when full config is not yet available."""
    try:
        manager = ConfigManager()
        repo_root = manager.find_repo_root(Path.cwd())
        config = manager.load(repo_root)
        logs_dir = flush.get_logs_dir(config, repo_root)
        flush.configure_logging(logs_dir / "flush.log")
        logger.error(flush._sanitize_for_log(message))
    except Exception as exc:
        logger.warning(
            "Best-effort error logging unavailable: %s", flush._sanitize_for_log(exc)
        )


def register(handlers: dict[str, Any]) -> None:
    """Register the SessionEnd handler with the hook dispatcher."""
    handlers["SessionEnd"] = _handle_session_end
