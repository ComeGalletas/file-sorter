"""Pure ingest helpers: hashing, discovery and frame probing (ING-001.1).

No database, no logging. Files are only ever opened for reading, and nothing here
prints or logs a path or a file name (CLAUDE.md "Hard rules").
"""

import hashlib
from pathlib import Path
from typing import NamedTuple

_CHUNK = 1024 * 1024
SHORT_HASH_LEN = 8  # R-ING-1


class FileHash(NamedTuple):
    source_hash: str
    short_hash: str


def hash_file(path: Path) -> FileHash:
    """SHA-256 of the file's bytes: the dedup key, and its first 8 hex chars (R-ING-1)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    source_hash = digest.hexdigest()
    return FileHash(source_hash, source_hash[:SHORT_HASH_LEN])
