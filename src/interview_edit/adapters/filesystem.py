from __future__ import annotations

import hashlib
from pathlib import Path

_FINGERPRINT_SAMPLE_SIZE = 256 * 1024


def quick_fingerprint(path: Path) -> str:
    stat = path.stat()
    digest = hashlib.sha256()
    digest.update(b"quick-sha256-v1\0")
    digest.update(str(stat.st_size).encode("ascii"))
    digest.update(b"\0")
    digest.update(str(stat.st_mtime_ns).encode("ascii"))
    offsets = {
        0,
        max(0, (stat.st_size - _FINGERPRINT_SAMPLE_SIZE) // 2),
        max(0, stat.st_size - _FINGERPRINT_SAMPLE_SIZE),
    }
    with path.open("rb") as handle:
        for offset in sorted(offsets):
            handle.seek(offset)
            chunk = handle.read(_FINGERPRINT_SAMPLE_SIZE)
            digest.update(b"\0offset\0")
            digest.update(str(offset).encode("ascii"))
            digest.update(b"\0")
            digest.update(chunk)
    return f"quick-sha256-v1:{digest.hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def full_sha256(path: Path) -> str:
    return f"sha256:{sha256_file(path)}"
