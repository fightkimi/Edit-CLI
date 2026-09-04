from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass(frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    return_code: int
    stdout: str
    stderr: str


class ProcessRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult: ...


class SubprocessRunner:
    def run(
        self,
        args: list[str],
        *,
        cwd: Path | None = None,
        timeout_seconds: float = 30,
    ) -> ProcessResult:
        try:
            completed = subprocess.run(
                args,
                cwd=cwd,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = _coerce_output(exc.stdout)
            stderr = _coerce_output(exc.stderr)
            return ProcessResult(tuple(args), 124, stdout, stderr or "command timed out")
        except OSError as exc:
            return ProcessResult(tuple(args), 127, "", str(exc))
        return ProcessResult(tuple(args), completed.returncode, completed.stdout, completed.stderr)


def _coerce_output(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
