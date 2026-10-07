"""The ingest node: write the ledger, skip known hashes, record duplicate paths (ING-001.2).

Batch-oriented and idempotent (P-4): re-running on a folder already ingested writes nothing
and reports every file as known. The node never commits; the caller owns the transaction.
It logs short hashes only, never a path (CLAUDE.md "Hard rules"). The container path is
stored in `files.source_path` and `files.duplicate_paths` and nowhere else (DOC-004.D3).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from classifier.graph.ingest_files import (
    SYMLINK,
    UNREADABLE_FOLDER,
    Candidate,
    FileHash,
    Probe,
    Skipped,
    discover,
    hash_file,
    probe_image,
)

log = logging.getLogger(__name__)

_EXT_MAX = 16  # files.ext is varchar(16)
_ERROR_STATUS = "error"

# R-ING-7: append the extra path to a known row, once. The WHERE clause is the whole check
# (not the error status, not the row's own path, not already listed), so it is one atomic
# statement and a concurrent run can't append twice.
_APPEND_DUPLICATE = """
update files
   set duplicate_paths = array_append(duplicate_paths, %(path)s), updated_at = now()
 where source_hash = %(hash)s
   and status <> 'error'
   and source_path <> %(path)s
   and not (%(path)s = any(duplicate_paths))
"""

_INSERT = """
insert into files (source_hash, short_hash, source_path, source_mtime, ext, status, animated, error)
values (%(hash)s, %(short)s, %(path)s, %(mtime)s, %(ext)s, %(status)s, %(animated)s, %(reason)s)
on conflict (source_hash) do nothing
"""

# R-ING-2: a row in `error` is retried: back to the start with the fresh facts.
_RETRY = """
update files
   set status = %(status)s, source_path = %(path)s, source_mtime = %(mtime)s, ext = %(ext)s,
       animated = %(animated)s, error = %(reason)s, updated_at = now()
 where source_hash = %(hash)s and status = 'error'
"""


@dataclass(frozen=True)
class IngestResult:
    """What one ingest run did. These fields are gate 1's contract (TST-002.4).

    Every walked file lands in exactly one count, so `total` is the number of files seen.
    On a re-run of an unchanged folder `new` is 0.
    """

    new: int = 0  # a `queued` row was written (a retried `error` row counts here too)
    skipped_known: int = 0  # the hash was already in the ledger: a no-op (R-ING-2)
    skipped_unreadable: int = 0  # not an image, undecodable, a symlink or an unreadable folder
    duplicate: int = 0  # this run appended a second path to a known row (R-ING-7)

    @property
    def total(self) -> int:
        return self.new + self.skipped_known + self.skipped_unreadable + self.duplicate


def ingest(conn: psycopg.Connection, root: Path) -> IngestResult:
    """Ingest every file under `root`, read-only, into the `files` ledger (R-ING-1 to R-ING-4).

    A new hash gets a `queued` row. A non-image or undecodable file is hashed and recorded
    as `skipped` with its reason in `files.error` (ING-001.D5). A symlink or an unreadable
    folder gets no row and counts as skipped-unreadable every run (ING-001.D6). A hash
    already known (any status but `error`) is a no-op, and the same hash at another path is
    appended to `duplicate_paths`.
    """
    counts = {"new": 0, "skipped_known": 0, "skipped_unreadable": 0, "duplicate": 0}
    for item in discover(root):
        counts[_ingest_one(conn, item)] += 1
    result = IngestResult(**counts)
    log.info(
        "ingest: %d new, %d known, %d unreadable, %d duplicate",
        result.new,
        result.skipped_known,
        result.skipped_unreadable,
        result.duplicate,
    )
    return result


def _ingest_one(conn: psycopg.Connection, item: Candidate | Skipped) -> str:
    """Record one discovered file and return the name of the count it falls in."""
    path = item.path
    if isinstance(item, Skipped) and not _hashable(item):
        return "skipped_unreadable"  # ING-001.D6: no row
    try:
        digest = hash_file(path)
    except OSError:
        return "skipped_unreadable"  # vanished or unreadable between the walk and the read

    # Duplicate or known: decided before decoding, so a known file is never decoded again.
    if _append_duplicate(conn, digest, path):
        log.info("ingest: duplicate path for %s", digest.short_hash)
        return "duplicate"
    status = _status(conn, digest)
    if status is not None and status != _ERROR_STATUS:
        return "skipped_known"

    try:
        row = _row(item, digest)
    except OSError:
        return "skipped_unreadable"  # vanished between the hash and the stat
    if status == _ERROR_STATUS:
        conn.execute(_RETRY, row)
        log.info("ingest: retried %s", digest.short_hash)
    elif conn.execute(_INSERT, row).rowcount == 0:
        # A concurrent run inserted the same hash first: it is known now, or a duplicate.
        return "duplicate" if _append_duplicate(conn, digest, path) else "skipped_known"
    return "new" if row["status"] == "queued" else "skipped_unreadable"


def _hashable(item: Skipped) -> bool:
    """A skipped entry is hashed only when it is a regular file we can read (ING-001.D6)."""
    return item.reason not in (SYMLINK, UNREADABLE_FOLDER)


def _append_duplicate(conn: psycopg.Connection, digest: FileHash, path: Path) -> bool:
    params = {"hash": digest.source_hash, "path": str(path)}
    return conn.execute(_APPEND_DUPLICATE, params).rowcount == 1


def _status(conn: psycopg.Connection, digest: FileHash) -> str | None:
    found = conn.execute(
        "select status from files where source_hash = %s", (digest.source_hash,)
    ).fetchone()
    return None if found is None else str(found[0])


def _row(item: Candidate | Skipped, digest: FileHash) -> dict[str, object]:
    """The column values for a new or retried row: `queued`, or `skipped` with its reason."""
    path = item.path
    outcome: Probe | Skipped = probe_image(path) if isinstance(item, Candidate) else item
    if isinstance(outcome, Probe):
        status, reason, animated, mtime = "queued", None, outcome.animated, outcome.mtime
    else:
        status, reason, animated = "skipped", outcome.reason, None
        mtime = _mtime(path)
    return {
        "hash": digest.source_hash,
        "short": digest.short_hash,
        "path": str(path),  # the container path as walked (DOC-004.D3)
        "mtime": mtime,
        "ext": path.suffix.lower().lstrip(".")[:_EXT_MAX],
        "status": status,
        "animated": animated,
        "reason": reason,
    }


def _mtime(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
