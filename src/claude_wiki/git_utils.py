"""Git helpers for inferring repository metadata from remotes."""

from __future__ import annotations

import subprocess
from pathlib import Path


def infer_repo_owner(repo_root: Path) -> str:
    """Infer repo_owner from the repo's origin remote URL.

    Supports common SSH and HTTPS forms and falls back to ``"local"`` when no
    remote is configured, git is unavailable, or the URL cannot be parsed.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return "local"

    if result.returncode != 0:
        return "local"

    url = result.stdout.strip()
    if not url:
        return "local"

    # SSH short form: git@github.com:<owner>/<repo>.git
    if url.startswith("git@"):
        rest = url.removeprefix("git@")
        for sep in (":", "/"):
            if sep in rest:
                path_part = rest.split(sep, 1)[1]
                break
        else:
            return "local"
        if path_part.endswith(".git"):
            path_part = path_part[:-4]
        parts = path_part.split("/")
        if len(parts) >= 2 and parts[0]:
            return parts[0]
        return "local"

    # HTTPS and ssh:// forms
    from urllib.parse import urlparse

    parsed = urlparse(url)
    path = parsed.path
    if path.startswith("/"):
        path = path[1:]
    if path.endswith(".git"):
        path = path[:-4]
    parts = path.split("/")
    if len(parts) >= 2 and parts[0]:
        return parts[0]

    return "local"
