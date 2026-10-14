"""The working copy in `.work/` and the write-new helper (FOP-001.1).

This module is the only place that removes or replaces a file under `.work/`: its own temp
files, and a stale working copy left by a crashed run for a `queued` row (R-FOP-6,
FOP-001.D1). The source is only ever opened for reading (R-FOP-1 step 1, R-SAN-1). Nothing
here logs or prints a path or a file name (CLAUDE.md "Hard rules").
"""

import errno
import hashlib
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO, NamedTuple

_CHUNK = 1024 * 1024
_SOURCE_HASH = re.compile(r"[0-9a-f]{64}")
_EXT = re.compile(r"[A-Za-z0-9]{1,16}")  # bare: no dot, no separator, so names stay in .work/


SOURCE_REFUSED = "the source file could not be opened as a regular file"  # fixed: never a path


TEMP_FAILED = "the temp file could not be opened for writing"  # fixed: never a path


class SourceRefusedError(OSError):
    """The original is missing, unreadable, a link or not a regular file (SAN-003.1.2).

    Fixed text only, raised unchained: an OS error's message carries the path.
    """


def working_copy_name(source_hash: str, ext: str) -> str:
    """`<source_hash>.<ext>`, the one name of a working copy in `.work/` (FOP-001.D1).

    Sanitize writes it and classify reads it, both through this function, so they agree by
    construction (CLS-002.D8). The hash and the extension are validated, so the name can never
    carry a separator or a traversal. Errors are fixed text: never the value.
    """
    if not _SOURCE_HASH.fullmatch(source_hash):
        raise ValueError("source_hash must be 64 lowercase hex characters")
    if not _EXT.fullmatch(ext):
        raise ValueError("ext must be a bare alphanumeric extension, without a dot")
    return f"{source_hash}.{ext}"


class WorkingCopy(NamedTuple):
    path: Path  # .work/<source_hash>.<ext>
    copy_sha256: str  # SHA-256 of the transformed copy, never the source_hash


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


def _close_quietly(fd: int) -> None:
    try:
        os.close(fd)
    except OSError:  # SAN-003.1.5: its message may hold a path; the caller raises fixed text
        pass


def _remove_quietly(path: Path) -> None:
    """Remove our own temp file; a failure is dropped so its path never escapes."""
    try:
        path.unlink(missing_ok=True)  # R-FOP-6: our own temp name
    except OSError:  # SAN-003.1.5
        pass


def _open_source(source: Path) -> BinaryIO:
    """Open an original for reading, refusing links and non-regular files (SAN-003.1.2).

    `O_NONBLOCK` keeps a FIFO from blocking the open. `O_NOFOLLOW` makes the kernel refuse a
    link at the last component, so there is no gap between a check and the open; `fstat` on
    the open fd then refuses a device, a pipe or a folder before any read. Any failure
    becomes `SourceRefusedError`, raised outside the
    handler so it carries no `__cause__` or `__context__`.
    """
    fd = -1
    handle = None
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
        if stat.S_ISREG(os.fstat(fd).st_mode):
            handle = os.fdopen(fd, "rb")
    except (OSError, ValueError):  # ValueError: a NUL or a lone surrogate in the path
        pass
    if handle is None:
        if fd >= 0:
            _close_quietly(fd)  # opened but refused, or fdopen failed: nothing owns it
        raise SourceRefusedError(SOURCE_REFUSED)
    return handle


def _new_temp(tmp: Path) -> BinaryIO:
    """Open `tmp` as a fresh file of our own, never through a link (SAN-001.D16).

    A leftover at that name (a crashed run's temp, or a planted symlink) is unlinked
    first, which removes the link itself and never its target. `O_EXCL | O_NOFOLLOW` then
    refuses anything that appears there meanwhile, so no write is ever redirected. Any
    failure (the unlink, the open, the `fdopen`) closes what was opened and raises
    `OSError(TEMP_FAILED)`: fixed text, unchained, never the temp's path (SAN-003.1.5).
    """
    fd = -1
    handle = None
    try:
        tmp.unlink(missing_ok=True)  # R-FOP-6: our own temp name
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
        fd = os.open(tmp, flags, 0o644)
        handle = os.fdopen(fd, "wb")
    except Exception:  # SAN-003.1.3: nothing owns the fd yet, so it is closed here
        pass
    if handle is None:
        if fd >= 0:  # we created the temp, so it is ours to remove
            _close_quietly(fd)
            _remove_quietly(tmp)
        raise OSError(TEMP_FAILED)  # fixed text, unchained
    return handle


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
    final = work_dir / working_copy_name(source_hash, ext)
    work_dir.mkdir(exist_ok=True)
    tmp = work_dir / f".{source_hash}.{ext}.tmp"  # FOP-001.D1; a crashed run's leftover is ours
    try:
        with _open_source(source) as src, _new_temp(tmp) as dst:
            while chunk := src.read(_CHUNK):
                dst.write(chunk)
            dst.flush()
            os.fsync(dst.fileno())
        transform(tmp)
        copy_sha256 = _sha256(tmp)
        os.replace(tmp, final)  # R-FOP-6: replaces only a stale working copy of this hash
    except BaseException:
        _remove_quietly(tmp)
        raise
    return WorkingCopy(final, copy_sha256)


# FOP-001.D2: the link can't be made on this filesystem (e.g. a Windows bind mount).
_NO_HARD_LINKS = frozenset({errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV})


def write_new(dest: Path, data: bytes) -> bool:
    """Write `data` to `dest` only if nothing is there yet; never replace a file.

    For small files such as thumbnails (ING-002). An existing `dest` is kept and nothing is
    written (ING-002.D2). Otherwise `data` goes to `.<name>.tmp` beside it and is published
    with `os.link`, which fails rather than replace a file that appeared meanwhile. Where
    hard links aren't supported, an `exists()` check and `os.rename` publish it instead
    (FOP-001.D2). Returns True if this call wrote `dest`. The temp file never outlives it.
    """
    if dest.exists():
        return False
    dest.parent.mkdir(exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.tmp")
    try:
        with _new_temp(tmp) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(tmp, dest)
        except FileExistsError:
            return False
        except OSError as exc:
            if exc.errno not in _NO_HARD_LINKS:
                raise
            # FOP-001.D2: the gap between the check and the rename is open only to a second
            # writer, which M2's single run excludes and the run lock (R-API-6) closes later.
            if dest.exists():
                return False
            os.rename(tmp, dest)
        return True
    finally:
        _remove_quietly(tmp)
