from enum import IntEnum


class ExitCode(IntEnum):
    SUCCESS = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2
    PREFLIGHT_FAILED = 3
    DEPENDENCY_MISSING = 4
    PATH_ERROR = 5
    INTERRUPTED = 130
