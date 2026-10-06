"""Pure ingest helpers: hashing, discovery and frame probing (ING-001.1).

No database, no logging. Files are only ever opened for reading, and nothing here
prints or logs a path or a file name (CLAUDE.md "Hard rules").
"""

import hashlib
import os
import struct
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import NamedTuple

from PIL import Image
from pillow_heif import register_heif_opener

register_heif_opener()  # R-ING-6: HEIC decodes through Pillow

_CHUNK = 1024 * 1024
SHORT_HASH_LEN = 8  # R-ING-1

# MVP image types (DESIGN.md §1). `tif` is an alias of `tiff` (ING-001.1.2).
IMAGE_EXTENSIONS = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".tiff", ".tif"}
)
# R-ING-8: ignored silently, with no ledger row and no log line. Compared lowercase.
OS_METADATA_NAMES = frozenset({"desktop.ini", "thumbs.db", ".ds_store"})
NOT_AN_IMAGE_TYPE = "not an image type"  # R-ING-3
SYMLINK = "symlink"  # ING-001.2.2


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
    case-insensitively) is a `Candidate`; any other file is `Skipped`, and so is a file
    symlink (ING-001.2.2). Nothing is opened, and symlinked directories are not followed.
    """
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            lowered = name.lower()
            if lowered in OS_METADATA_NAMES:
                continue
            path = Path(dirpath) / name
            if path.is_symlink():  # ING-001.2.2: it may point outside the root; never follow it
                yield Skipped(path, SYMLINK)
            elif Path(lowered).suffix in IMAGE_EXTENSIONS:
                yield Candidate(path)
            else:
                yield Skipped(path, NOT_AN_IMAGE_TYPE)


# R-ING-9 / ING-001.D3 (decided by the human): an allow-list. PNG covers APNG. Every other
# format is never animated, including TIFF, MPO and HEIC.
_ANIMATED_FORMATS = frozenset({"GIF", "WEBP", "PNG"})


# What Pillow raises for a file it can't decode: OSError covers UnidentifiedImageError and
# truncation, SyntaxError and struct.error come from format plugins, EOFError from short reads.
_PILLOW_ERRORS = (
    OSError,
    EOFError,
    SyntaxError,
    ValueError,
    struct.error,
    Image.DecompressionBombError,
)


class Probe(NamedTuple):
    """What decoding the first frame or page told us about a file."""

    width: int
    height: int
    format: str
    animated: bool
    mtime: datetime  # source mtime, UTC (R-ING-4)


def probe_image(path: Path) -> Probe | Skipped:
    """Decode the first frame or page (R-ING-6) and derive `animated` (R-ING-9).

    The sole judge of decodability: a file that can't be decoded, or is truncated, comes
    back as `Skipped` (R-ING-3) and never raises. The reason carries the exception type
    only, because Pillow's messages can contain the path.
    """
    try:
        with Image.open(path) as image:
            image.load()  # first frame or page; raises on a truncated file
            animated = image.format in _ANIMATED_FORMATS and bool(
                getattr(image, "is_animated", False)
            )
            probe = Probe(
                width=image.width,
                height=image.height,
                format=image.format or "",
                animated=animated,
                mtime=datetime.fromtimestamp(path.stat().st_mtime, tz=UTC),
            )
    except _PILLOW_ERRORS as exc:  # anything else is a bug and must surface (ING-001.2.1)
        return Skipped(path, f"undecodable image ({type(exc).__name__})")
    return probe
