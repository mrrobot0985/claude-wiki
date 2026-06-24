"""Pure unit tests for ConfigManager path/config resolution."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from claude_wiki.config import ConfigManager
from claude_wiki.errors import ConfigError
from claude_wiki.models import ProjectConfig


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
        """Find repo root by walking up to .claude-wiki.lock marker."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            (repo / ".claude-wiki.lock").write_text('{"repo_name": "test"}')
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
        """Load config from existing .claude-wiki.lock."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            marker = repo / ".claude-wiki.lock"
            marker.write_text(
                json.dumps(
                    {
                        "repo_name": "my-project",
                        "repo_owner": "owner",
                        "layout_version": "2",
                        "kb_dir": "custom-kb",
                        "daily_dir": "custom-daily",
                        "timezone": "Europe/Amsterdam",
                        "compile_after_hour": 21,
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
            assert config.compile_after_hour == 21

    def test_load_env_override_precedence_after_lock_data(self):
        """CLAUDE_WIKI_DAILY_DIR overrides the lock value, not the other way around."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            marker = repo / ".claude-wiki.lock"
            marker.write_text(
                json.dumps(
                    {
                        "repo_name": "my-project",
                        "repo_owner": "owner",
                        "layout_version": "2",
                        "kb_dir": "project",
                        "daily_dir": "lock-daily",
                        "timezone": "UTC",
                        "compile_after_hour": 18,
                    }
                )
            )

            with patch.dict(
                os.environ,
                {"CLAUDE_WIKI_DAILY_DIR": str(repo / "env-daily")},
                clear=False,
            ):
                manager = ConfigManager()
                config = manager.load(repo)
                assert config.daily_dir == repo / "env-daily"

    def test_load_relative_env_override_anchored_to_repo_root(self):
        """Relative CLAUDE_WIKI_PROJECT_DIR is anchored at repo_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            with patch.dict(
                os.environ, {"CLAUDE_WIKI_PROJECT_DIR": "env-kb"}, clear=False
            ):
                manager = ConfigManager()
                config = ProjectConfig(repo_name="test", repo_owner="owner")
                kb_root = manager.get_kb_root(repo, config)
                assert kb_root == repo / "env-kb"

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
            assert config.kb_dir == Path("project")
            assert config.daily_dir == Path(".claude/daily")
            assert config.timezone == "UTC"

    def test_write_marker(self):
        """Write .claude-wiki.lock marker file."""
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

            marker = repo / ".claude-wiki.lock"
            assert marker.exists()
            data = json.loads(marker.read_text())
            assert data["repo_name"] == "my-project"
            assert data["kb_dir"] == "kb"

    def test_get_kb_root_project_mode(self):
        """Default 'project' mode resolves to repo_root/.claude/knowledge."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            manager = ConfigManager()
            config = ProjectConfig(repo_name="my-project", repo_owner="owner")
            kb_root = manager.get_kb_root(repo, config)
            assert kb_root == repo / ".claude" / "knowledge"

    def test_get_kb_root_user_mode(self):
        """Explicit 'user' mode resolves to XDG path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"XDG_DATA_HOME": tmpdir}, clear=False):
                repo = Path(tmpdir) / "my-project"
                repo.mkdir()
                manager = ConfigManager()
                config = ProjectConfig(
                    repo_name="my-project", repo_owner="owner", kb_dir=Path("user")
                )
                kb_root = manager.get_kb_root(repo, config)
                expected = Path(tmpdir) / "claude-wiki-vault" / "owner" / "my-project"
                assert kb_root == expected

    def test_get_kb_root_env_override(self):
        """CLAUDE_WIKI_PROJECT_DIR env var overrides KB root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            override = Path(tmpdir) / "custom-kb"
            with patch.dict(
                os.environ, {"CLAUDE_WIKI_PROJECT_DIR": str(override)}, clear=False
            ):
                manager = ConfigManager()
                config = ProjectConfig(repo_name="test", repo_owner="owner")
                kb_root = manager.get_kb_root(repo, config)
                assert kb_root == override

    def test_get_kb_root_absolute_in_config(self):
        """Absolute kb_dir in config is used verbatim."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            absolute_kb = Path(tmpdir) / "absolute-kb"
            manager = ConfigManager()
            config = ProjectConfig(
                repo_name="test", repo_owner="owner", kb_dir=absolute_kb
            )
            kb_root = manager.get_kb_root(repo, config)
            assert kb_root == absolute_kb

    def test_get_kb_root_relative_path(self):
        """Custom relative kb_dir is anchored at repo_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            manager = ConfigManager()
            config = ProjectConfig(
                repo_name="test", repo_owner="owner", kb_dir=Path("custom-kb")
            )
            kb_root = manager.get_kb_root(repo, config)
            assert kb_root == repo / "custom-kb"

    def test_get_kb_root_returns_absolute_resolved_path(self):
        """get_kb_root always returns an absolute, resolved Path in every branch."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            repo = base / "repo"
            repo.mkdir()
            manager = ConfigManager()

            # Env override with a parent-directory component resolves clean.
            env_path = base / "env" / ".." / "override-kb"
            with patch.dict(
                os.environ, {"CLAUDE_WIKI_PROJECT_DIR": str(env_path)}, clear=False
            ):
                config = ProjectConfig(repo_name="r", repo_owner="o")
                result = manager.get_kb_root(repo, config)
                assert result.is_absolute()
                assert result == (base / "override-kb").resolve(strict=False)

            # Absolute config path with a parent-directory component resolves clean.
            cfg_path = base / "cfg" / ".." / "config-kb"
            config = ProjectConfig(repo_name="r", repo_owner="o", kb_dir=cfg_path)
            result = manager.get_kb_root(repo, config)
            assert result.is_absolute()
            assert result == (base / "config-kb").resolve(strict=False)

            # User mode resolves under XDG_DATA_HOME.
            with patch.dict(os.environ, {"XDG_DATA_HOME": str(base)}, clear=False):
                config = ProjectConfig(
                    repo_name="r", repo_owner="o", kb_dir=Path("user")
                )
                result = manager.get_kb_root(repo, config)
                assert result.is_absolute()
                assert result == (base / "claude-wiki-vault" / "o" / "r").resolve(
                    strict=False
                )

            # Project mode resolves under repo_root.
            config = ProjectConfig(
                repo_name="r", repo_owner="o", kb_dir=Path("project")
            )
            result = manager.get_kb_root(repo, config)
            assert result.is_absolute()
            assert result == (repo / ".claude" / "knowledge").resolve(strict=False)

            # Relative fallback anchored at repo_root resolves clean.
            config = ProjectConfig(repo_name="r", repo_owner="o", kb_dir=Path("rel-kb"))
            result = manager.get_kb_root(repo, config)
            assert result.is_absolute()
            assert result == (repo / "rel-kb").resolve(strict=False)

    def test_write_uses_pid_suffixed_temp_file(self):
        """write() uses a pid-suffixed temp file to avoid collision."""
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

            marker = repo / ".claude-wiki.lock"
            assert marker.exists()
            # There should be no leftover temp files.
            temps = list(repo.glob(".lock.tmp*"))
            assert temps == []

    def test_write_persists_atomically_with_utf8_and_replace(self):
        """write() creates a sibling temp file, writes UTF-8, and os.replace()s it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            manager = ConfigManager()
            config = ProjectConfig(
                repo_name="my-project",
                repo_owner="owner",
                kb_dir=Path("kb-百科"),
                daily_dir=Path("daily"),
                timezone="UTC",
            )

            original_write_text = Path.write_text
            writes: list[tuple[Path, str | None]] = []

            def tracking_write_text(
                self: Path,
                data: str,
                encoding: str | None = None,
                errors: str | None = None,
                newline: str | None = None,
            ) -> None:
                if self.parent == repo and self.name != ".claude-wiki.lock":
                    writes.append((self, encoding))
                return original_write_text(
                    self, data, encoding=encoding, errors=errors, newline=newline
                )

            original_replace = os.replace
            replacements: list[tuple[Path, Path]] = []

            def tracking_replace(src: str | Path, dst: str | Path) -> None:
                replacements.append((Path(src), Path(dst)))
                return original_replace(src, dst)

            with patch("pathlib.Path.write_text", tracking_write_text):
                with patch(
                    "claude_wiki.config.os.replace", side_effect=tracking_replace
                ):
                    manager.write(repo, config)

            marker = repo / ".claude-wiki.lock"
            assert marker.exists()
            assert len(writes) == 1
            temp_path, encoding = writes[0]
            assert encoding == "utf-8"
            assert temp_path.parent == repo
            assert temp_path != marker
            assert len(replacements) == 1
            assert replacements[0] == (temp_path, marker)

            data = json.loads(marker.read_text(encoding="utf-8"))
            assert data["repo_name"] == "my-project"
            assert data["repo_owner"] == "owner"
            assert data["kb_dir"] == "kb-百科"

    def test_load_corrupt_marker_raises_config_error_with_path(self):
        """A corrupt .claude-wiki.lock raises ConfigError with the absolute path and JSON text."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "my-project"
            repo.mkdir()
            marker = repo / ".claude-wiki.lock"
            marker.write_text("{not valid json", encoding="utf-8")

            manager = ConfigManager()
            with pytest.raises(ConfigError) as exc_info:
                manager.load(repo)

            message = str(exc_info.value)
            assert str(marker.resolve(strict=False)) in message
            assert "Expecting property name" in message

    def test_get_kb_root_expands_tilde_in_env_and_config(self):
        """Tilde in env override and config paths is expanded to HOME."""
        with tempfile.TemporaryDirectory() as tmpdir:
            home_dir = Path(tmpdir) / "home"
            home_dir.mkdir()
            (home_dir / "env-kb").mkdir()
            (home_dir / "config-kb").mkdir()
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            manager = ConfigManager()

            with patch.dict(
                os.environ,
                {"HOME": str(home_dir), "CLAUDE_WIKI_PROJECT_DIR": "~/env-kb"},
                clear=False,
            ):
                result = manager.get_kb_root(
                    repo, ProjectConfig(repo_name="r", repo_owner="o")
                )
                assert result == (home_dir / "env-kb").resolve(strict=False)

            with patch.dict(os.environ, {"HOME": str(home_dir)}, clear=False):
                config = ProjectConfig(
                    repo_name="r", repo_owner="o", kb_dir=Path("~/config-kb")
                )
                result = manager.get_kb_root(repo, config)
                assert result == (home_dir / "config-kb").resolve(strict=False)


class TestResolveRepoPath:
    """Unit tests for ConfigManager.resolve_repo_path."""

    def test_resolve_path_relative_against_repo_root(self):
        """Relative paths are resolved against repo_root when provided."""
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = Path(tmpdir) / "repo"
            repo.mkdir()
            resolved = ConfigManager.resolve_repo_path(Path("kb"), repo)
            assert resolved == (repo / "kb").resolve(strict=False)

    def test_resolve_path_relative_without_repo_root(self):
        """Relative paths resolve against cwd when repo_root is absent."""
        original_cwd = os.getcwd()
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                base = Path(tmpdir).resolve()
                os.chdir(base)
                resolved = ConfigManager.resolve_repo_path(Path("kb"), None)
                assert resolved == (base / "kb").resolve(strict=False)
        finally:
            os.chdir(original_cwd)

    def test_resolve_path_absolute_unchanged(self):
        """Absolute paths are returned resolved and unaffected by repo_root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            base = Path(tmpdir).resolve()
            absolute = base / "external" / "kb"
            resolved = ConfigManager.resolve_repo_path(absolute, base / "repo")
            assert resolved == absolute.resolve(strict=False)
            assert resolved.is_absolute()


class TestProjectConfig:
    """Pure unit tests for ProjectConfig validation and serialization."""

    def test_path_defaults_are_distinct_instances(self):
        """Each instance gets its own Path objects for directory defaults."""
        cfg1 = ProjectConfig(repo_name="a")
        cfg2 = ProjectConfig(repo_name="b")

        assert cfg1.kb_dir is not cfg2.kb_dir
        assert cfg1.daily_dir is not cfg2.daily_dir
        assert cfg1.reports_dir is not cfg2.reports_dir

    def test_default_constructed_config_passes_validation(self):
        """ProjectConfig(repo_name=...) with defaults is valid."""
        config = ProjectConfig(repo_name="my-project")

        assert config.repo_name == "my-project"
        assert config.repo_owner == "local"
        assert config.kb_dir == Path("project")
        assert config.daily_dir == Path("daily")
        assert config.reports_dir == Path("reports")
        assert config.timezone == "UTC"
        assert config.compile_after_hour == 18

    def test_from_dict_roundtrip(self):
        """from_dict/to_dict preserve values and serialize Paths as strings."""
        config = ProjectConfig.from_dict(
            {
                "repo_name": "my-project",
                "repo_owner": "owner",
                "kb_dir": "custom-kb",
                "daily_dir": "custom-daily",
                "reports_dir": "custom-reports",
                "timezone": "Europe/Amsterdam",
                "compile_after_hour": 21,
            }
        )

        assert config.repo_name == "my-project"
        assert config.repo_owner == "owner"
        assert config.kb_dir == Path("custom-kb")
        assert config.daily_dir == Path("custom-daily")
        assert config.reports_dir == Path("custom-reports")
        assert config.timezone == "Europe/Amsterdam"
        assert config.compile_after_hour == 21

        serialized = config.to_dict()
        assert serialized["kb_dir"] == "custom-kb"
        assert serialized["daily_dir"] == "custom-daily"
        assert serialized["reports_dir"] == "custom-reports"

    def test_from_dict_missing_repo_name_raises_config_error(self):
        """Missing repo_name raises ConfigError with a clear message."""
        with pytest.raises(ConfigError, match="repo_name"):
            ProjectConfig.from_dict({})

    def test_from_dict_empty_repo_name_raises_config_error(self):
        """Empty repo_name raises ConfigError."""
        with pytest.raises(ConfigError, match="repo_name"):
            ProjectConfig.from_dict(
                {
                    "repo_name": "",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_whitespace_repo_name_raises_config_error(self):
        """Whitespace-only repo_name is treated as empty."""
        with pytest.raises(ConfigError, match="repo_name"):
            ProjectConfig.from_dict(
                {
                    "repo_name": "   ",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_non_string_repo_name_raises_config_error(self):
        """Non-string repo_name raises ConfigError."""
        with pytest.raises(ConfigError, match="repo_name"):
            ProjectConfig.from_dict(
                {
                    "repo_name": 123,
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_empty_repo_owner_raises_config_error(self):
        """Empty repo_owner raises ConfigError."""
        with pytest.raises(ConfigError, match="repo_owner"):
            ProjectConfig.from_dict(
                {
                    "repo_name": "x",
                    "repo_owner": "",
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_non_string_repo_owner_raises_config_error(self):
        """Non-string repo_owner raises ConfigError."""
        with pytest.raises(ConfigError, match="repo_owner"):
            ProjectConfig.from_dict(
                {
                    "repo_name": "x",
                    "repo_owner": 123,
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_missing_compile_after_hour_raises_config_error(self):
        """Missing compile_after_hour raises ConfigError."""
        with pytest.raises(ConfigError, match="compile_after_hour"):
            ProjectConfig.from_dict({"repo_name": "x", "repo_owner": "local"})

    def test_from_dict_non_int_compile_after_hour_raises_config_error(self):
        """Non-int compile_after_hour raises ConfigError."""
        with pytest.raises(ConfigError, match="compile_after_hour"):
            ProjectConfig.from_dict(
                {
                    "repo_name": "x",
                    "repo_owner": "local",
                    "compile_after_hour": "evening",
                }
            )

    @pytest.mark.parametrize("hour", [-1, 24])
    def test_from_dict_out_of_range_compile_after_hour_raises_config_error(self, hour):
        """compile_after_hour outside 0..23 raises ConfigError."""
        with pytest.raises(ConfigError, match="compile_after_hour"):
            ProjectConfig.from_dict(
                {
                    "repo_name": "x",
                    "repo_owner": "local",
                    "compile_after_hour": hour,
                }
            )

    @pytest.mark.parametrize(
        "field_name",
        ["repo_name", "repo_owner", "timezone", "compile_after_hour"],
    )
    def test_from_dict_null_required_field_raises_config_error(self, field_name):
        """JSON null for a required/typed field raises ConfigError, not TypeError."""
        data = {
            "repo_name": "x",
            "repo_owner": "local",
            "timezone": "UTC",
            "compile_after_hour": 18,
            field_name: None,
        }
        with pytest.raises(ConfigError, match=field_name):
            ProjectConfig.from_dict(data)

    @pytest.mark.parametrize("dir_field", ["kb_dir", "daily_dir", "reports_dir"])
    def test_from_dict_invalid_path_type_raises_config_error(self, dir_field):
        """Non-string/non-Path directory values raise ConfigError."""
        data = {
            "repo_name": "x",
            "repo_owner": "local",
            "compile_after_hour": 18,
            dir_field: 123,
        }
        with pytest.raises(ConfigError, match=dir_field):
            ProjectConfig.from_dict(data)

    def test_from_dict_accepts_path_objects(self):
        """Path values for directory fields are accepted directly."""
        config = ProjectConfig.from_dict(
            {
                "repo_name": "x",
                "repo_owner": "local",
                "compile_after_hour": 18,
                "kb_dir": Path("custom-kb"),
                "daily_dir": Path("custom-daily"),
                "reports_dir": Path("custom-reports"),
            }
        )

        assert config.kb_dir == Path("custom-kb")
        assert config.daily_dir == Path("custom-daily")
        assert config.reports_dir == Path("custom-reports")
