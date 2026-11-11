"""The one run lock (DB-007.1; R-API-6, C-11).

A session-level Postgres advisory lock on one fixed key (DB-007.D1): it lasts until it is
released or the connection closes, so the per-node commits of a run (PIPE-001.D3) never drop
it. Hold it on a connection that lives as long as the run.
"""

from sqlalchemy import Connection, text

# DB-007.D1: one fixed key, pinned by the tests. Any bigint works; this one spells "fsrunlck".
RUN_LOCK_KEY = 0x667372756E6C636B

_TRY = text("select pg_try_advisory_lock(:key)")
_RELEASE = text("select pg_advisory_unlock(:key)")


def try_run_lock(conn: Connection) -> bool:
    """Take the run lock without waiting. True if this session now holds it."""
    return bool(conn.execute(_TRY, {"key": RUN_LOCK_KEY}).scalar_one())


def release_run_lock(conn: Connection) -> None:
    """Release the run lock held by this session. A no-op if it isn't held here."""
    conn.execute(_RELEASE, {"key": RUN_LOCK_KEY})
