"""The working copy in `.work/` (FOP-001.1).

This module is the only place that removes or replaces a file under `.work/`: its own temp
files, and a stale working copy left by a crashed run for a `queued` row (R-FOP-6,
FOP-001.D1). The source is only ever opened for reading (R-FOP-1 step 1, R-SAN-1). Nothing
here logs or prints a path or a file name (CLAUDE.md "Hard rules").
"""

import hashlib
import os
import re
from collections.abc import Callable
from pathlib import Path
from typing import NamedTuple

_CHUNK = 1024 * 1024
_SOURCE_HASH = re.compile(r"[0-9a-f]{64}")
_EXT = re.compile(r"[A-Za-z0-9]{1,16}")  # bare: no dot, no separator, so names stay in .work/


class WorkingCopy(NamedTuple):
    path: Path  # .work/<source_hash>.<ext>
    copy_sha256: str  # SHA-256 of the transformed copy, never the source_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def make_working_copy(
    source: Path,
    work_dir: Path,
    source_hash: str,
    ext: str,
    transform: Callable[[Path], None],
) -> WorkingCopy:
    """Copy `source` into `work_dir`, run `transform` on the copy, then publish it.

    The copy goes to `.<source_hash>.<ext>.tmp`, `transform` (the metadata strip) works on
    that temp file and raises to abort, and only then is it renamed atomically to
    `<source_hash>.<ext>` (FOP-001.D1). A stale copy under that name is replaced. On any
    failure the temp file is removed and the exception propagates, so a file that didn't
    pass `transform` never appears under the final name.
    """
    if not _SOURCE_HASH.fullmatch(source_hash):
        raise ValueError("source_hash must be 64 lowercase hex characters")
    if not _EXT.fullmatch(ext):
        raise ValueError("ext must be a bare alphanumeric extension, without a dot")
    work_dir.mkdir(exist_ok=True)
    final = work_dir / f"{source_hash}.{ext}"
    tmp = work_dir / f".{source_hash}.{ext}.tmp"  # FOP-001.D1; a crashed run's leftover is ours
    try:
        with source.open("rb") as src, tmp.open("wb") as dst:
            while chunk := src.read(_CHUNK):
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        transform(tmp)
        copy_sha256 = _sha256(tmp)
        os.replace(tmp, final)  # R-FOP-6: replaces only a stale working copy of this hash
    except BaseException:
        tmp.unlink(missing_ok=True)  # R-FOP-6: our own temp file
        raise
    return WorkingCopy(final, copy_sha256)
