"""Domain-specific exceptions. Lightweight taxonomy."""


class ClaudeKBError(RuntimeError):
    """Base for all package-level errors."""


class RepoNotFoundError(ClaudeKBError):
    """Raised when a repository root cannot be determined."""


class ConfigError(ClaudeKBError):
    """Raised when configuration is missing, malformed, or unreadable."""


class WriterError(ClaudeKBError):
    """Raised when an LLM-produced article fails validation or would escape kb_root."""


class CompileError(ClaudeKBError):
    """Raised when a compile step fails in a way that may still incur cost.

    ``cost_usd`` is set when the failure happened after the LLM call so the
    caller can record the spend and mark the log for retry or manual review.
    """

    def __init__(self, message: str, *, cost_usd: float | None = None) -> None:
        super().__init__(message)
        self.cost_usd = cost_usd
