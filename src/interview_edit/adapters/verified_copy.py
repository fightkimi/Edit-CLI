from __future__ import annotations

import hashlib
import os
import tempfile
from collections.abc import Callable
from pathlib import Path

from interview_edit.errors import PreflightError


def copy_verified(
    source: Path,
    destination: Path,
    expected: str,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    """Copy into a private file; publish only the exact expected bytes, never hard-link media."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    total = source.stat().st_size
    copied = 0
    digest = hashlib.sha256()
    try:
        with (
            source.open("rb") as reader,
            tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as writer,
        ):
            temporary = Path(writer.name)
            while chunk := reader.read(8 * 1024 * 1024):
                writer.write(chunk)
                digest.update(chunk)
                copied += len(chunk)
                if progress is not None:
                    progress(copied, total)
            writer.flush()
            os.fsync(writer.fileno())
        if digest.hexdigest() != expected:
            raise PreflightError(
                "jianying_source_changed", "Resource differs from the captured input."
            )
        os.replace(temporary, destination)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
