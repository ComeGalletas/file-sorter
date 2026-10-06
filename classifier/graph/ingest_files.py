"""Pure ingest helpers: hashing, discovery and frame probing (ING-001.1).

No database, no logging. Files are only ever opened for reading, and nothing here
prints or logs a path or a file name (CLAUDE.md "Hard rules").
"""

import hashlib
import os
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

_CHUNK = 1024 * 1024
SHORT_HASH_LEN = 8  # R-ING-1

# MVP image types (DESIGN.md §1). `tif` is an alias of `tiff` (ING-001.1.2).
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tiff", ".tif"}
)
# R-ING-8: ignored silently, with no ledger row and no log line. Compared lowercase.
OS_METADATA_NAMES = frozenset({"desktop.ini", "thumbs.db", ".ds_store"})
NOT_AN_IMAGE_TYPE = "not an image type"  # R-ING-3


class Candidate(NamedTuple):
    """A file with an MVP image extension. Whether it decodes is `probe_image`'s call."""

    path: Path


class Skipped(NamedTuple):
    """A file the ledger records as `skipped` (R-ING-3). `reason` never contains a path."""

    path: Path
    reason: str


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


def discover(root: Path) -> Iterator[Candidate | Skipped]:
    """Walk `root` recursively and read-only, in sorted order (R-ING-3, R-ING-8).

    OS metadata files are dropped silently. A file with an MVP image extension (matched
    case-insensitively) is a `Candidate`; any other file is `Skipped`. Nothing is opened,
    and symlinked directories are not followed.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            lowered = name.lower()
            if lowered in OS_METADATA_NAMES:
                continue
            path = Path(dirpath) / name
            if Path(lowered).suffix in IMAGE_EXTENSIONS:
                yield Candidate(path)
            else:
                yield Skipped(path, NOT_AN_IMAGE_TYPE)
