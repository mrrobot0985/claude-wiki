"""Pure unit tests for ConfigManager (RepoDetector + ConfigLoader)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_kb.config import ConfigManager
from claude_kb.models import ProjectConfig


class TestConfigManager:
    """Tests for ConfigManager path resolution and marker file handling."""

    def test_find_repo_root_from_git(self):
        """Find repo root by walking up to .git directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()
            subdir = repo / "src" / "deep"
            subdir.mkdir(parents=True)

            manager = ConfigManager()
            found = manager.find_repo_root(subdir)
            assert found == repo.resolve()

    def test_find_repo_root_from_marker(self):
        """Find repo root by walking up to .claude-wiki.json marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".claude-wiki.json").write_text('{"repo_name": "test"}')
            subdir = repo / "src" / "deep"
            subdir.mkdir(parents=True)

            manager = ConfigManager()
            found = manager.find_repo_root(subdir)
            assert found == repo.resolve()

    def test_find_repo_root_raises_when_not_found(self):
        """Raise error when no .git or marker found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            manager = ConfigManager()
            with pytest.raises(RuntimeError, match="Not in a git repo"):
                manager.find_repo_root(Path(tmpdir))

    def test_load_existing_marker(self):
        """Load config from existing .claude-wiki.json."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            marker = repo / ".claude-wiki.json"
            marker.write_text(
                json.dumps(
                    {
                        "repo_name": "my-project",
                        "repo_owner": "owner",
                        "kb_dir": "custom-kb",
                        "daily_dir": "custom-daily",
                        "timezone": "Europe/Amsterdam",
                    }
                )
            )

            manager = ConfigManager()
            config = manager.load(repo)

            assert config.repo_name == "my-project"
            assert config.repo_owner == "owner"
            assert config.kb_dir == Path("custom-kb")
            assert config.daily_dir == Path("custom-daily")
            assert config.timezone == "Europe/Amsterdam"

    def test_load_defaults_when_no_marker(self):
        """Load defaults when no marker exists."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".git").mkdir()

            manager = ConfigManager()
            config = manager.load(repo)

            assert config.repo_name == "my-project"
            assert config.repo_owner == "local"
            assert config.kb_dir == Path("knowledge")
            assert config.daily_dir == Path("daily")
            assert config.timezone == "UTC"

    def test_write_marker(self):
        """Write .claude-wiki.json marker file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()

            manager = ConfigManager()
            config = ProjectConfig(
                repo_name="my-project",
                repo_owner="owner",
                kb_dir=Path("kb"),
                daily_dir=Path("daily"),
                timezone="UTC",
            )
            manager.write(repo, config)

            marker = repo / ".claude-wiki.json"
            assert marker.exists()
            data = json.loads(marker.read_text())
            assert data["repo_name"] == "my-project"
            assert data["kb_dir"] == "kb"

    def test_get_kb_root_xdg_default(self):
        """Get KB root using XDG default."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"XDG_DATA_HOME": tmpdir}, clear=False):
                manager = ConfigManager()
                config = ProjectConfig(repo_name="my-project", repo_owner="owner")
                kb_root = manager.get_kb_root(config)
                expected = Path(tmpdir) / "claude-wiki" / "owner" / "my-project"
                assert kb_root == expected

    def test_get_kb_root_env_override(self):
        """CLAUDE_WIKI_PROJECT_DIR env var overrides KB root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            override = Path(tmpdir) / "custom-kb"
            with patch.dict(
                os.environ, {"CLAUDE_WIKI_PROJECT_DIR": str(override)}, clear=False
            ):
                manager = ConfigManager()
                config = ProjectConfig(repo_name="test", repo_owner="owner")
                kb_root = manager.get_kb_root(config)
                assert kb_root == override

    def test_get_kb_root_absolute_in_config(self):
        """Absolute kb_dir in config takes precedence over XDG."""
        with tempfile.TemporaryDirectory() as tmpdir:
            absolute_kb = Path(tmpdir) / "absolute-kb"
            manager = ConfigManager()
            config = ProjectConfig(
                repo_name="test", repo_owner="owner", kb_dir=absolute_kb
            )
            kb_root = manager.get_kb_root(config)
            assert kb_root == absolute_kb
