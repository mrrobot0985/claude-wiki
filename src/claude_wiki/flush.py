"""Core flush logic shared by the SessionEnd and PreCompact hooks.

The hook handlers perform only fast local I/O and spawn a background process
that imports this module via ``python -m claude_wiki.flush``.  Keeping the core
logic in one place makes it easy to test and reuse for both hook events.
"""

from __future__ import annotations

import argparse
import asyncio
import fcntl
import json
import logging
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from claude_wiki.config import ConfigManager
from claude_wiki.models import ProjectConfig

logger = logging.getLogger("claude_wiki.flush")

DEFAULT_MAX_TURNS = 30
DEFAULT_MAX_CONTEXT_CHARS = 15_000
DEFAULT_MIN_TURNS_TO_FLUSH = 1

# Non-blocking daily-log lock: bounded retries so a peer holding the lock
# cannot block this process indefinitely.
_DAILY_LOG_LOCK_RETRIES = 10
_DAILY_LOG_LOCK_RETRY_INTERVAL = 0.1


@contextmanager
def _daily_log_lock(lock_path: Path) -> Iterator[None]:
    """Advisory lock protecting daily-log read-modify-write cycles.

    Uses a non-blocking acquire with bounded retries so a peer holding the
    lock cannot block this process indefinitely; raises ``TimeoutError`` if
    the lock cannot be acquired within the retry budget.

    On Windows this is a no-op because ``fcntl`` is unavailable.
    """
    if sys.platform == "win32":
        yield
        return

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as lock_file:
        acquired = False
        for _ in range(_DAILY_LOG_LOCK_RETRIES):
            try:
                fcntl.lockf(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except BlockingIOError:
                time.sleep(_DAILY_LOG_LOCK_RETRY_INTERVAL)
        if not acquired:
            raise TimeoutError(f"timed out acquiring daily log lock at {lock_path}")
        try:
            yield
        finally:
            fcntl.lockf(lock_file.fileno(), fcntl.LOCK_UN)


def configure_logging(log_path: Path) -> None:
    """Configure file-based logging, creating parent directories as needed."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        filename=str(log_path),
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        force=True,
    )


def read_hook_input(raw: str) -> dict[str, Any]:
    """Parse the JSON payload Claude Code sends to a hook on stdin.

    Claude Code on Windows may pass paths with unescaped backslashes; this
    function falls back to a minimal escape fix if the first parse fails.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        fixed = re.sub(r'(?<!\\)\\(?!["\\])', r"\\\\", raw)
        data = json.loads(fixed)

    if not isinstance(data, dict):
        raise ValueError("hook input is not a JSON object")
    return data


def extract_conversation_context(
    transcript_path: Path,
    *,
    max_turns: int = DEFAULT_MAX_TURNS,
    max_chars: int = DEFAULT_MAX_CONTEXT_CHARS,
) -> tuple[str, int]:
    """Read a JSONL transcript and extract the last *N* user/assistant turns.

    Returns a tuple of ``(markdown_context, turn_count)``.
    """
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

    recent = turns[-max_turns:] if max_turns else []
    context = "\n".join(recent)

    if len(context) > max_chars:
        context = context[-max_chars:]
        boundary = context.find("\n**")
        if boundary > 0:
            context = context[boundary + 1 :]

    return context, len(recent)


def write_context_file(
    cache_dir: Path,
    session_id: str,
    context: str,
    *,
    prefix: str = "session-flush",
) -> Path:
    """Persist extracted context for the background flush process."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d-%H%M%S")
    context_file = cache_dir / f"{prefix}-{session_id}-{timestamp}.md"
    context_file.write_text(context, encoding="utf-8")
    return context_file


def get_logs_dir(config: ProjectConfig, repo_root: Path) -> Path:
    """Return the per-machine logs directory used for logs and state."""
    manager = ConfigManager()
    state_dir = manager.get_machine_state_dir(repo_root, config)
    return state_dir / "logs"


def spawn_flush(
    context_file: Path,
    session_id: str,
    repo_root: Path,
    *,
    executable: str | None = None,
) -> subprocess.Popen[Any]:
    """Spawn ``python -m claude_wiki.flush`` as a detached background process."""
    if executable is None:
        executable = sys.executable

    cmd = [
        str(executable),
        "-m",
        "claude_wiki.flush",
        str(context_file),
        session_id,
        str(repo_root),
    ]

    kwargs: dict[str, Any] = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    return subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )


def load_flush_state(state_file: Path) -> dict[str, Any]:
    """Load the lightweight deduplication/state file."""
    if state_file.exists():
        try:
            data = json.loads(state_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _write_file_atomic(target: Path, content: str) -> None:
    """Write *content* to *target* atomically via a same-directory temp file."""
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        delete=False,
        dir=target.parent,
        suffix=".tmp",
    )
    try:
        tmp.write(content)
        tmp.close()
        os.replace(tmp.name, target)
    except Exception:
        Path(tmp.name).unlink(missing_ok=True)
        raise


def save_flush_state(state_file: Path, state: dict[str, Any]) -> None:
    """Persist the deduplication/state file."""
    _write_file_atomic(state_file, json.dumps(state))


def append_to_daily_log(
    content: str,
    repo_root: Path,
    config: ProjectConfig,
    *,
    section: str = "Session",
    lock_path: Path | None = None,
) -> Path:
    """Append a flushed entry to today's daily log in the repository."""
    today = datetime.now(timezone.utc).astimezone()
    log_path = repo_root / config.daily_dir / f"{today.strftime('%Y-%m-%d')}.md"

    log_path.parent.mkdir(parents=True, exist_ok=True)

    def _append() -> None:
        if log_path.exists():
            existing = log_path.read_text(encoding="utf-8")
        else:
            existing = (
                f"# Daily Log: {today.strftime('%Y-%m-%d')}\n\n"
                "## Sessions\n\n## Memory Maintenance\n\n"
            )

        time_str = today.strftime("%H:%M")
        entry = f"### {section} ({time_str})\n\n{content}\n\n"
        _write_file_atomic(log_path, existing + entry)

    if lock_path is not None:
        with _daily_log_lock(lock_path):
            _append()
    else:
        _append()

    return log_path


async def _run_flush_with_sdk(context: str, repo_root: Path) -> str:
    """Use the Claude Agent SDK to decide what is worth saving."""
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ResultMessage,
        TextBlock,
        query,
    )

    prompt = f"""Review the conversation context below and respond with a concise summary
of important items that should be preserved in the daily log.
Do NOT use any tools — just return plain text.

Format your response as a structured daily log entry with these sections:

**Context:** [One line about what the user was working on]

**Key Exchanges:**
- [Important Q&A or discussions]

**Decisions Made:**
- [Any decisions with rationale]

**Lessons Learned:**
- [Gotchas, patterns, or insights discovered]

**Action Items:**
- [Follow-ups or TODOs mentioned]

Skip anything that is:
- Routine tool calls or file reads
- Content that's trivial or obvious
- Trivial back-and-forth or clarification exchanges

Only include sections that have actual content. If nothing is worth saving,
respond with exactly: FLUSH_OK

## Conversation Context

{context}"""

    response = ""
    try:
        async for message in query(
            prompt=prompt,
            options=ClaudeAgentOptions(
                cwd=str(repo_root),
                allowed_tools=[],
                max_turns=2,
            ),
        ):
            if isinstance(message, AssistantMessage):
                for block in message.content:
                    if isinstance(block, TextBlock):
                        response += block.text
            elif isinstance(message, ResultMessage):
                pass
    except Exception as e:
        import traceback

        logger.error("Agent SDK error: %s\n%s", e, traceback.format_exc())
        response = f"FLUSH_ERROR: {type(e).__name__}: {e}"

    return response


def run_flush(context: str, repo_root: Path) -> str:
    """Run the LLM extraction synchronously."""
    return asyncio.run(_run_flush_with_sdk(context, repo_root))


def flush_main(
    argv: list[str] | None = None,
    *,
    runner: Callable[[str, Path], str] | None = None,
) -> int:
    """Background entry point: ``python -m claude_wiki.flush <ctx> <session> <repo>``."""
    parser = argparse.ArgumentParser(prog="claude_wiki.flush")
    parser.add_argument("context_file", type=Path)
    parser.add_argument("session_id")
    parser.add_argument("repo_root", type=Path)
    args = parser.parse_args(argv)

    context_file: Path = args.context_file
    session_id: str = args.session_id
    repo_root: Path = args.repo_root.resolve()

    # Recursion guard: set this as early as possible so any nested Claude
    # invocation triggered by the Agent SDK does not re-run the hooks.
    os.environ["CLAUDE_INVOKED_BY"] = "memory_flush"

    manager = ConfigManager()
    config = manager.load(repo_root)

    state_dir = manager.get_machine_state_dir(repo_root, config)
    lock_path = state_dir / "daily.log.lock"

    logs_dir = get_logs_dir(config, repo_root)
    logs_dir.mkdir(parents=True, exist_ok=True)
    configure_logging(logs_dir / "flush.log")

    logger.info(
        "flush.py started for session %s, context: %s", session_id, context_file
    )

    if not context_file.exists():
        logger.error("Context file not found: %s", context_file)
        return 1

    state_file = logs_dir / "last-flush.json"
    state = load_flush_state(state_file)
    if (
        state.get("session_id") == session_id
        and time.time() - state.get("timestamp", 0) < 60
    ):
        logger.info("Skipping duplicate flush for session %s", session_id)
        context_file.unlink(missing_ok=True)
        return 0

    context = context_file.read_text(encoding="utf-8").strip()
    if not context:
        logger.info("Context file is empty, skipping")
        context_file.unlink(missing_ok=True)
        return 0

    logger.info("Flushing session %s: %d chars", session_id, len(context))

    response = runner(context, repo_root) if runner else run_flush(context, repo_root)

    if "FLUSH_OK" in response:
        logger.info("Result: FLUSH_OK")
        append_to_daily_log(
            "FLUSH_OK - Nothing worth saving from this session",
            repo_root,
            config,
            section="Memory Flush",
            lock_path=lock_path,
        )
    elif "FLUSH_ERROR" in response:
        logger.error("Result: %s", response)
        append_to_daily_log(
            response, repo_root, config, section="Memory Flush", lock_path=lock_path
        )
    else:
        logger.info("Result: saved to daily log (%d chars)", len(response))
        append_to_daily_log(response, repo_root, config, lock_path=lock_path)

    save_flush_state(state_file, {"session_id": session_id, "timestamp": time.time()})
    context_file.unlink(missing_ok=True)

    logger.info("Flush complete for session %s", session_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(flush_main())
