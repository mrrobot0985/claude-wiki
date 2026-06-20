"""Shared pytest fixtures for the claude-wiki test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _isolate_user_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Redirect HOME and all XDG directories to a per-test tmp area.

    Without this, any un-patched ``GlobalIndexManager()`` / ``platformdirs``
    call resolves to the developer's *live* ``~/.local/share`` (because
    ``XDG_DATA_HOME`` is set in the real environment) and the suite silently
    mutates the real vault registry and ``~/.claude`` settings. Pointing every
    well-known directory at a throwaway tmp path makes the suite hermetic by
    default so no test can touch real user state regardless of whether it
    remembers to patch the right symbol.
    """
    home = tmp_path / "home"
    data = home / ".local" / "share"
    state = home / ".local" / "state"
    config = home / ".config"
    cache = home / ".cache"
    for path in (data, state, config, cache):
        path.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("XDG_STATE_HOME", str(state))
