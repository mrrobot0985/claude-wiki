"""Interactive prompts for claude-wiki init — no external dependencies."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from claude_wiki.models import ProjectConfig


def is_interactive() -> bool:
    """Return True when stdin is connected to a terminal."""
    return sys.stdin.isatty()


def prompt(
    text: str,
    default: str | None = None,
    validator: Callable[[str], bool] | None = None,
) -> str:
    """Prompt for a string value with an optional default and validator.

    Empty input accepts the default when one is provided. Invalid input
    re-prompts with a brief error. ``EOFError`` aborts the prompt when no
    default exists.
    """
    while True:
        default_part = f" [{default}]" if default is not None else ""
        try:
            answer = input(f"{text}{default_part}: ")
        except EOFError:
            if default is not None:
                return default
            raise

        answer = answer.strip()
        if not answer and default is not None:
            answer = default

        if validator is not None and not validator(answer):
            print("Invalid input. Please try again.")
            continue

        return answer


def choice(text: str, options: list[str], default: str | None = None) -> str:
    """Prompt for one of the allowed options (case-insensitive)."""
    normalized = {opt.lower(): opt for opt in options}

    # Map non-option defaults (e.g. an absolute custom path) to a placeholder
    # option so the user sees the actual value pre-selected.
    if default is not None and default.lower() not in normalized:
        default = "custom"

    def validator(answer: str) -> bool:
        return answer.lower() in normalized

    display = prompt(
        f"{text} ({'/'.join(options)})", default=default, validator=validator
    )
    return normalized[display.lower()]


def confirm(text: str, default: bool = False) -> bool:
    """Prompt for a yes/no answer."""
    default_str = "Y/n" if default else "y/N"
    default_val = "y" if default else "n"
    answer = prompt(f"{text} ({default_str})", default=default_val)
    return answer.lower() in ("y", "yes")


def configure(
    repo_root: Path,
    defaults: ProjectConfig,
) -> tuple[ProjectConfig, bool]:
    """Run interactive prompts and return a fully populated config + hook target.

    The second return value is ``True`` when the user chooses global hook
    installation, otherwise ``False``.
    """
    print("\nConfiguring claude-wiki for this repository.\n")

    owner = prompt(
        "Repo owner",
        default=defaults.repo_owner,
        validator=lambda answer: bool(answer.strip()),
    )

    kb_mode = choice(
        "KB directory mode",
        options=["project", "user", "custom"],
        default=str(defaults.kb_dir),
    )
    if kb_mode == "custom":
        kb_dir = prompt(
            "Custom KB path",
            default=str(defaults.kb_dir),
            validator=lambda answer: bool(answer.strip()),
        )
    else:
        kb_dir = kb_mode

    daily_dir = prompt(
        "Daily log directory",
        default=str(defaults.daily_dir),
        validator=lambda answer: bool(answer.strip()),
    )

    def _timezone_validator(answer: str) -> bool:
        if not answer.strip():
            return False
        try:
            ZoneInfo(answer)
        except ZoneInfoNotFoundError:
            return False
        return True

    timezone = prompt(
        "Timezone",
        default=defaults.timezone,
        validator=_timezone_validator,
    )

    def _hour_validator(answer: str) -> bool:
        try:
            return 0 <= int(answer) <= 23
        except ValueError:
            return False

    compile_hour = int(
        prompt(
            "Compile after hour (0-23)",
            default=str(defaults.compile_after_hour),
            validator=_hour_validator,
        )
    )

    hook_target = choice(
        "Hook installation target",
        options=["repo-local", "global"],
        default="repo-local",
    )

    config = ProjectConfig(
        repo_name=defaults.repo_name,
        repo_owner=owner,
        kb_dir=Path(kb_dir),
        daily_dir=Path(daily_dir),
        reports_dir=defaults.reports_dir,
        timezone=timezone,
        compile_after_hour=compile_hour,
    )
    return config, hook_target == "global"
