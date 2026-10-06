"""Ledger queries and the CSV writer behind `classifier dry-run` (CLI-002.1, R-PIPE-2).

CLI-002.D1: the CSV lists ledger rows under the scanned root, not per-run outcomes. The
container path in `source_path` is allowed in `results_root/reports/` only (DOC-004.D3);
nothing here prints or logs it.
"""

import csv
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import NamedTuple

import psycopg

COLUMNS = ("source_hash", "short_hash", "source_path", "status", "reason", "proposed_output")

# `starts_with`, not LIKE: a root containing `%` or `_` must match literally.
_UNDER_ROOT = """
select source_hash, short_hash, source_path, status, error
  from files
 where starts_with(source_path, %(prefix)s)
 order by source_path, source_hash
"""


class LedgerRow(NamedTuple):
    source_hash: str
    short_hash: str
    source_path: str
    status: str
    reason: str | None


def _prefix(source_root: str) -> str:
    return str(PurePosixPath(source_root)).rstrip("/") + "/"


def rows_under_root(conn: psycopg.Connection, source_root: str) -> list[LedgerRow]:
    """Every `files` row whose `source_path` lies under `source_root`, by path (CLI-002.D1)."""
    with conn.cursor() as cur:
        cur.execute(_UNDER_ROOT, {"prefix": _prefix(source_root)})
        return [LedgerRow(*row) for row in cur.fetchall()]


def skip_reasons(rows: Sequence[LedgerRow]) -> dict[str, int]:
    """Count the `skipped` rows by their reason; the reasons are fixed text, never a path."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.status == "skipped":
            key = row.reason or "unknown"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def report_path(results_root: str, stamp: datetime) -> Path:
    """`results_root/reports/dry-run-<UTC run timestamp>.csv`."""
    return Path(results_root) / "reports" / f"dry-run-{stamp:%Y%m%dT%H%M%SZ}.csv"


def write_csv(path: Path, rows: Sequence[LedgerRow]) -> None:
    """Write the report; `proposed_output` stays empty until M1 sets none (PIPE-001.D1)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(COLUMNS)
        for row in rows:
            writer.writerow(
                [row.source_hash, row.short_hash, row.source_path, row.status, row.reason or "", ""]
            )
