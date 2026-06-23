"""Tests for claude_wiki domain models."""

import dataclasses
from pathlib import Path

import pytest

from claude_wiki.errors import ConfigError
from claude_wiki.models import (
    CompileResult,
    FlushResult,
    LintResult,
    MigrationResult,
    ProjectConfig,
    QueryResult,
    _field_default,
)


class TestFieldDefault:
    """Tests for _field_default helper."""

    def test_field_default_raises_for_required_field(self):
        """A required field with no default raises ConfigError."""
        field = dataclasses.fields(ProjectConfig)[0]  # repo_name
        assert field.default is dataclasses.MISSING
        assert field.default_factory is dataclasses.MISSING
        with pytest.raises(ConfigError):
            _field_default(field)

    def test_field_default_returns_default_value(self):
        """A field with a scalar default returns that default."""
        owner_field = next(
            f for f in dataclasses.fields(ProjectConfig) if f.name == "repo_owner"
        )
        assert _field_default(owner_field) == "local"

    def test_field_default_calls_factory(self):
        """A field with a default_factory calls the factory."""
        kb_field = next(
            f for f in dataclasses.fields(ProjectConfig) if f.name == "kb_dir"
        )
        assert _field_default(kb_field) == Path("project")


class TestProjectConfigValidation:
    """Tests for ProjectConfig construction and from_dict validation."""

    def test_post_init_rejects_empty_repo_name(self):
        """An empty repo_name raises ConfigError from __post_init__."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="")

    def test_post_init_rejects_non_string_repo_owner(self):
        """A non-string repo_owner raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", repo_owner=123)

    def test_post_init_rejects_non_string_layout_version(self):
        """A non-string layout_version raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", layout_version=123)

    def test_post_init_rejects_empty_layout_version(self):
        """An empty layout_version string raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", layout_version="  ")

    def test_post_init_rejects_empty_timezone(self):
        """An empty timezone string raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", timezone="  ")

    def test_post_init_rejects_compile_hour_below_range(self):
        """compile_after_hour below 0 raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", compile_after_hour=-1)

    def test_post_init_rejects_compile_hour_above_range(self):
        """compile_after_hour above 23 raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", compile_after_hour=24)

    def test_post_init_rejects_non_int_compile_hour(self):
        """A non-integer compile_after_hour raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", compile_after_hour="18")

    def test_post_init_rejects_invalid_path_type(self):
        """A kb_dir that is neither str nor Path raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", kb_dir=123)

    def test_from_dict_rejects_null_value(self):
        """A null value for a known field raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict({"repo_name": None})

    def test_from_dict_requires_repo_name(self):
        """Missing repo_name in dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict({"repo_owner": "local"})

    def test_from_dict_requires_compile_after_hour(self):
        """Missing compile_after_hour in dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict({"repo_name": "test"})

    def test_from_dict_rejects_invalid_compile_hour(self):
        """Out-of-range compile_after_hour from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {"repo_name": "test", "repo_owner": "local", "compile_after_hour": 99}
            )

    def test_from_dict_rejects_empty_repo_name(self):
        """Empty repo_name from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "  ",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_rejects_non_string_repo_owner(self):
        """A non-string repo_owner from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": 123,
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_rejects_empty_repo_owner(self):
        """Empty repo_owner from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "  ",
                    "compile_after_hour": 18,
                }
            )

    def test_from_dict_rejects_non_string_layout_version(self):
        """A non-string layout_version from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                    "layout_version": 123,
                }
            )

    def test_from_dict_rejects_empty_layout_version(self):
        """Empty layout_version from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                    "layout_version": "  ",
                }
            )

    def test_from_dict_preserves_layout_version(self):
        """An explicit layout_version in dict is preserved."""
        config = ProjectConfig.from_dict(
            {
                "repo_name": "test",
                "repo_owner": "local",
                "compile_after_hour": 18,
                "layout_version": "2",
            }
        )
        assert config.layout_version == "2"

    def test_from_dict_rejects_empty_timezone(self):
        """Empty timezone from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                    "timezone": "  ",
                }
            )

    def test_from_dict_rejects_invalid_timezone(self):
        """A timezone that is not a real IANA zone from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                    "timezone": "Mars/Phobos",
                }
            )

    def test_from_dict_rejects_compile_hour_below_range(self):
        """compile_after_hour below 0 from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": -1,
                }
            )

    def test_from_dict_rejects_non_int_compile_hour(self):
        """A non-integer compile_after_hour from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": "18",
                }
            )

    def test_from_dict_rejects_invalid_path_type(self):
        """A kb_dir that is neither str nor Path from dict raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig.from_dict(
                {
                    "repo_name": "test",
                    "repo_owner": "local",
                    "compile_after_hour": 18,
                    "kb_dir": 123,
                }
            )

    def test_default_layout_version_is_two(self):
        """Default layout_version for a fresh ProjectConfig is '2'."""
        config = ProjectConfig(repo_name="test")
        assert config.layout_version == "2"

    def test_from_dict_converts_string_path(self):
        """String path values in dict are converted to Path."""
        config = ProjectConfig.from_dict(
            {
                "repo_name": "test",
                "repo_owner": "local",
                "compile_after_hour": 18,
                "kb_dir": "my-kb",
            }
        )
        assert config.kb_dir == Path("my-kb")

    def test_to_dict_serializes_paths(self):
        """to_dict converts Path values to strings."""
        config = ProjectConfig(repo_name="test", kb_dir=Path("my-kb"))
        data = config.to_dict()
        assert data["kb_dir"] == "my-kb"
        assert data["repo_name"] == "test"

    def test_post_init_rejects_invalid_timezone(self):
        """A timezone string that is not a real IANA zone raises ConfigError."""
        with pytest.raises(ConfigError):
            ProjectConfig(repo_name="test", timezone="Mars/Phobos")

    def test_post_init_expands_user_daily_dir(self):
        """A leading ~ in daily_dir is expanded to the user's home (issue #46)."""
        config = ProjectConfig(repo_name="test", daily_dir=Path("~/.claude/daily"))
        assert config.daily_dir == Path.home() / ".claude" / "daily"
        assert "~" not in config.daily_dir.parts

    def test_from_dict_expands_user_daily_dir(self):
        """A leading ~ in a string daily_dir is expanded via from_dict (issue #46)."""
        config = ProjectConfig.from_dict(
            {
                "repo_name": "test",
                "repo_owner": "local",
                "compile_after_hour": 18,
                "daily_dir": "~/.claude/daily",
            }
        )
        assert config.daily_dir == Path.home() / ".claude" / "daily"
        assert "~" not in config.daily_dir.parts


class TestResultModels:
    """Smoke tests for lightweight result dataclasses."""

    def test_compile_result_defaults(self):
        result = CompileResult(
            files_processed=1, articles_created=1, articles_updated=0
        )
        assert result.errors == []

    def test_query_result_defaults(self):
        result = QueryResult(answer="yes")
        assert result.citations == []
        assert result.confidence == 0.0

    def test_lint_result_defaults(self):
        result = LintResult()
        assert result.errors == []
        assert result.warnings == []
        assert result.suggestions == []

    def test_flush_result_defaults(self):
        result = FlushResult()
        assert result.concepts_extracted == 0

    def test_migration_result_defaults(self):
        result = MigrationResult(migrated=False)
        assert result.errors == []
        assert result.warnings == []
        assert result.rolled_back == []
