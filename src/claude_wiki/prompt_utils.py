"""Prompt-safe wrapping helpers.

Avoids user-supplied markdown (daily logs, KB articles) from closing the
prompt's own code fences.
"""

from __future__ import annotations

import re


def _max_backtick_run(text: str) -> int:
    """Return the length of the longest run of consecutive backticks in ``text``."""
    return max((len(m) for m in re.findall(r"`+", text)), default=0)


def _wrap_for_prompt(content: str, *, info: str = "markdown") -> str:
    """Wrap ``content`` in a markdown fence longer than any backtick run inside it.

    This prevents content containing triple backticks from closing the
    surrounding code fence early and leaking into the rest of the prompt.
    """
    fence_len = max(3, _max_backtick_run(content) + 1)
    fence = "`" * fence_len
    return f"{fence}{info}\n{content}\n{fence}"
