"""API-001.3: read one thumbnail from `<results_root>/.work/thumbs/<source_hash>.webp`.

The thumbnails are ING-002's, made from the sanitized working copy, never from an original
(m4 answer 3). The caller passes a hash it read back from the ledger, never client text
(m4 privacy item 13). Every refusal returns None, with no exception kept: a folder that
isn't the real `.work/thumbs`, a symlink, a non-regular file, an oversized file and any
`OSError` all look the same, so the route can answer one fixed 404 (API-001.D12).
"""

import os
import re
import stat
from pathlib import Path

# The sanitize node's folder names (ING-002.D1). They are repeated here, not imported, so
# the API doesn't pull in the node's model clients; tests/unit/api pins them to the node's.
WORK_DIR = ".work"
THUMBS_DIR = "thumbs"
THUMB_SUFFIX = ".webp"
THUMB_MEDIA_TYPE = "image/webp"
MAX_THUMB_BYTES = 4 * 1024 * 1024  # a thumbnail is a few KiB

_HASH = re.compile(r"[0-9a-f]{64}")
_OPEN_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | getattr(os, "O_CLOEXEC", 0)


def is_source_hash(value: str) -> bool:
    """A full lowercase SHA-256 hex digest, the ledger's `source_hash` shape."""
    return _HASH.fullmatch(value) is not None


def thumbs_folder(results_root: Path) -> Path | None:
    """The real `.work/thumbs` under `results_root`, or None if a part links elsewhere."""
    try:
        root = results_root.resolve(strict=True)
        folder = (results_root / WORK_DIR / THUMBS_DIR).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if folder != root / WORK_DIR / THUMBS_DIR:
        return None
    return folder


def _read_regular(path: Path) -> bytes | None:
    try:
        # O_NOFOLLOW: a symlink fails to open. O_NONBLOCK: a FIFO can't hang the request.
        fd = os.open(path, _OPEN_FLAGS)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_THUMB_BYTES:
            return None
        chunks: list[bytes] = []
        total = 0
        while total <= MAX_THUMB_BYTES:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
    except OSError:
        return None
    finally:
        os.close(fd)
    if total > MAX_THUMB_BYTES:  # it grew after the fstat
        return None
    return b"".join(chunks)


def read_thumbnail(results_root: Path, ledger_hash: str) -> bytes | None:
    """The thumbnail's bytes for a hash the ledger holds, or None on any refusal or miss."""
    if not is_source_hash(ledger_hash):
        return None
    folder = thumbs_folder(results_root)
    if folder is None:
        return None
    return _read_regular(folder / f"{ledger_hash}{THUMB_SUFFIX}")
