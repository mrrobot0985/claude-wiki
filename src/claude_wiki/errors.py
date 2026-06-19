"""Domain-specific exceptions. Lightweight taxonomy."""


class ClaudeKBError(RuntimeError):
    """Base for all package-level errors."""


class RepoNotFoundError(ClaudeKBError):
    """Raised when a repository root cannot be determined."""


class ConfigError(ClaudeKBError):
    """Raised when configuration is missing, malformed, or unreadable."""


class HookRegistrationError(ClaudeKBError):
    """Raised when global hook installation fails."""
