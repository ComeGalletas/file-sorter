"""The one way a row past `queued` moves to `error` (SAN-003.D2, generalising SAN-001.D18).

The row's `sanitize_log` rows go in the same savepoint, so a retry from ingest (R-ING-2),
which re-sanitizes the file, never doubles them. `reason` is stored in `files.error` and
must be a fixed string some node registered: an exception message, which may hold a path or
a name, is refused. Never commits; `run` commits once per node (PIPE-001.D3).
"""

from collections.abc import Collection, Iterable

import psycopg

# Each node registers its fixed reasons at import; CLS-002.2 adds its own.
_REASONS: set[str] = set()

# PIPE-001.D2: the node overwrites its own column on failure; a retry from ingest rewrites
# `original_sanitized` along with the log (R-ING-2).
_MARK_ERROR = """
update files
   set status = 'error', error = %s, original_sanitized = null, updated_at = now()
 where source_hash = %s and status = any(%s)
"""
_CLEAR_LOG = "delete from sanitize_log where source_hash = %s"


def register_reasons(reasons: Iterable[str]) -> None:
    """Allow these fixed reasons in `mark_error` (idempotent)."""
    _REASONS.update(reasons)


def mark_error(
    conn: psycopg.Connection, source_hash: str, reason: str, *, from_statuses: Collection[str]
) -> bool:
    """Move the row from one of `from_statuses` to `error`, clearing its `sanitize_log`.

    Returns True if the row moved, False if it wasn't in one of those statuses (nothing is
    touched then). Raises `ValueError` with fixed text for a reason no node registered.
    """
    if reason not in _REASONS:
        raise ValueError("mark_error: reason is not a registered fixed reason (SAN-003.D2)")
    with conn.transaction():  # a savepoint: run's transaction is already open
        moved = conn.execute(_MARK_ERROR, (reason, source_hash, list(from_statuses))).rowcount
        if moved:
            conn.execute(_CLEAR_LOG, (source_hash,))
    return moved == 1
