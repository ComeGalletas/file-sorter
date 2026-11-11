"""API-001.4: the dashboard's and review queue's selects.

Each one narrows `views.rows_query`, so API-001.1's column allowlist stays the only list of
columns the UI reads (ING-001.D2, m4 privacy item 11), with its newest-first order.
"""

from sqlalchemy import Connection, or_

from classifier.api.views import PER_PAGE, FileFilters, FileRow, file_row, rows_query
from classifier.db.models import File
from classifier.models.classify_rules import UNSORTED

LATEST = 20  # API-001.D1: "latest" in a dry run, "filed" from M7


def _rows(conn: Connection, query: object) -> list[FileRow]:
    return [file_row(m) for m in conn.execute(query).mappings()]  # type: ignore[call-overload]


def _offset(page: int) -> int:
    return (page - 1) * PER_PAGE


def latest_rows(conn: Connection) -> list[FileRow]:
    return _rows(conn, rows_query(FileFilters()).limit(LATEST))


def error_rows(conn: Connection, page: int) -> list[FileRow]:
    """API-001.D2: rows with an error code, newest first, 50 per page (lead, #214)."""
    query = rows_query(FileFilters()).where(File.error.is_not(None))
    return _rows(conn, query.limit(PER_PAGE).offset(_offset(page)))


def review_rows(conn: Connection, page: int) -> list[FileRow]:
    """API-001.D9: `needs_review`, or the unsorted fallback format; 50 per page."""
    queued = or_(File.needs_review.is_(True), File.format == UNSORTED)
    query = rows_query(FileFilters()).where(queued)
    return _rows(conn, query.limit(PER_PAGE).offset(_offset(page)))
