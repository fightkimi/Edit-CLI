from collections.abc import Mapping
from typing import Any

from interview_edit.exit_codes import ExitCode


class InterviewEditError(Exception):
    """An expected error with a stable machine code and process exit code."""

    def __init__(
        self,
        code: str,
        message: str,
        exit_code: ExitCode,
        *,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code
        self.details = dict(details or {})


class UsageError(InterviewEditError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, ExitCode.USAGE_ERROR, details=details)


class PathSafetyError(InterviewEditError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, ExitCode.PATH_ERROR, details=details)


class DependencyError(InterviewEditError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, ExitCode.DEPENDENCY_MISSING, details=details)


class PreflightError(InterviewEditError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, ExitCode.PREFLIGHT_FAILED, details=details)


class ProcessingError(InterviewEditError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(code, message, ExitCode.RUNTIME_ERROR, details=details)
