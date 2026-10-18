"""Ledger queries and the CSV writer behind `classifier dry-run` (CLI-002.1, R-PIPE-2).

CLI-002.D1: the CSV lists ledger rows under the scanned root, not per-run outcomes. The
container path in `source_path` is allowed in `results_root/reports/` only (DOC-004.D3);
nothing here prints or logs it. `sanitized_name` sits beside it (CLI-003.1, ING-001.D2
option A, DOC-007.D1): `files.original_sanitized`, empty until the sanitize node sets it.
"""

import csv
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath

import psycopg

from classifier.config import Config
from classifier.fileops.folders import FolderSyncError, topic_chain
from classifier.fileops.layout import LayoutError, result_folder
from classifier.models.classify_rules import UNSORTED, CategoryRule

COLUMNS = (
    "source_hash",
    "short_hash",
    "source_path",
    "sanitized_name",
    "status",
    "reason",
    "proposed_output",
    "format",
    "topic",
    "branch",
    "needs_review",
    "review_reason",
    "proposed_folder",
)

# `starts_with`, not LIKE: a root containing `%` or `_` must match literally.
_UNDER_ROOT = """
select source_hash, short_hash, source_path, original_sanitized, status, error,
       format, topic, branch, needs_review, review_reason, animated
  from files
 where starts_with(source_path, %(prefix)s)
 order by source_path, source_hash
"""


REPORT_WRITE_FAILED = "the dry-run report could not be written (results_root/reports)"


class ReportWriteError(Exception):
    """The report folder or file could not be created or written (SAN-003.3). Fixed text only."""


REPORT_FOLDER_FAILED = "the dry-run report could not compute a result folder (categories, folders)"


class ReportFolderError(ReportWriteError):
    """A row's result folder cannot be built (CLI-005.1). Fixed text only; the ledger is written."""


@dataclass(frozen=True)
class LedgerRow:
    """One `files` row as the report sees it. The path and every name or category are hidden
    from `repr`, so a stray log of a row leaks nothing (CLI-005.1, DOC-007.D1)."""

    source_hash: str
    short_hash: str
    source_path: str = field(repr=False)
    sanitized_name: str | None = field(repr=False)
    status: str
    reason: str | None
    format: str | None = field(default=None, repr=False)
    topic: str | None = field(default=None, repr=False)
    branch: str | None = None
    needs_review: bool | None = None
    review_reason: str | None = None  # a fixed code (`unsorted`)
    animated: bool | None = None


FolderOf = Callable[[LedgerRow], str]


def prefix_for(source_root: str) -> str:
    return str(PurePosixPath(source_root)).rstrip("/") + "/"


def rows_under_root(conn: psycopg.Connection, source_root: str) -> list[LedgerRow]:
    """Every `files` row whose `source_path` lies under `source_root`, by path (CLI-002.D1)."""
    with conn.cursor() as cur:
        cur.execute(_UNDER_ROOT, {"prefix": prefix_for(source_root)})
        return [LedgerRow(*row) for row in cur.fetchall()]  # column order = LedgerRow fields


def skip_reasons(rows: Sequence[LedgerRow]) -> dict[str, int]:
    """Count the `skipped` rows by their reason; the reasons are fixed text, never a path."""
    counts: dict[str, int] = {}
    for row in rows:
        if row.status == "skipped":
            key = row.reason or "unknown"
            counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


_RULES = "select id, axis, name, folder, min_score, branch, parent_id from categories order by id"


def folder_resolver(conn: psycopg.Connection, config: Config) -> FolderOf:
    """`row -> proposed folder` from FOP-002.1's `result_folder` (CLI-005.D1); never stored.

    Empty for a row not `classified` yet, or whose category was removed since (DB-003.D1).
    Any other problem raises `ReportFolderError`, a fixed text, unchained.
    """
    rules = [
        CategoryRule(
            id=int(i),
            axis=str(axis),
            name=str(name),
            folder=str(folder),
            min_score=None if score is None else float(score),
            branch=str(branch),
            parent_id=None if parent is None else int(parent),
        )
        for i, axis, name, folder, score, branch, parent in conn.execute(_RULES).fetchall()
    ]
    formats = {r.name: r for r in rules if r.axis == "format"}
    topics = {r.id: r for r in rules if r.axis == "topic"}
    by_name = {r.name: r for r in topics.values()}

    def folder_of(row: LedgerRow) -> str:
        if row.status != "classified" or row.format is None:
            return ""
        fmt = formats.get(row.format)
        topic = by_name.get(row.topic) if row.topic is not None else None
        if fmt is None or (row.topic is not None and topic is None):
            return ""
        problem = False
        folder = ""
        try:
            chain = topic_chain(topic, topics) if topic is not None else []
            folder = result_folder(
                branch="nsfw" if row.branch == "nsfw" else "safe",
                topic_path=[t.folder for t in chain],
                format_folder=None if fmt.name == UNSORTED else fmt.folder,
                animated=bool(row.animated),
                folders=config.folders,
                nsfw_root=config.nsfw.root,
            ).as_posix()
        except (LayoutError, FolderSyncError):
            problem = True
        if problem:
            raise ReportFolderError(REPORT_FOLDER_FAILED)
        return folder

    return folder_of


def report_path(results_root: str, stamp: datetime, attempt: int = 0) -> Path:
    """`results_root/reports/dry-run-<UTC run timestamp>[-<attempt>].csv`."""
    suffix = f"-{attempt}" if attempt else ""
    return Path(results_root) / "reports" / f"dry-run-{stamp:%Y%m%dT%H%M%SZ}{suffix}.csv"


def write_csv(
    results_root: str,
    stamp: datetime,
    rows: Sequence[LedgerRow],
    folder_of: FolderOf | None = None,
) -> Path:
    """Write the report and return its path; `proposed_output` stays empty (PIPE-001.D1).

    `proposed_folder` comes from `folder_of`, computed for every row before anything is
    written, and the whole file is encoded in memory before it is created (CLI-005.1.4). So a
    folder problem or an unencodable character leaves no report, not even a header. The file is
    UTF-8 with `surrogateescape`: a non-UTF-8 name is written back as its original bytes. Any
    other lone surrogate is a `ReportWriteError`, fixed text. If the write itself fails after
    the file was created (a full disk, say), the partial file is left in place, because deleting
    is `fileops/delete.py`'s alone (CLAUDE.md); the fixed error is raised, and a re-run writes
    a new report under the next free name.

    The file is opened exclusively, so two runs in the same second never overwrite each
    other: the later one gets a numeric suffix.
    """
    folders = [folder_of(row) if folder_of else "" for row in rows]
    failed = False  # SAN-003.3: an OSError message carries the path; raise fixed text after
    path = report_path(results_root, stamp)
    try:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer)
        writer.writerow(COLUMNS)
        for row, folder in zip(rows, folders, strict=True):
            writer.writerow(
                [
                    row.source_hash,
                    row.short_hash,
                    row.source_path,
                    row.sanitized_name or "",
                    row.status,
                    row.reason or "",
                    "",
                    row.format or "",
                    row.topic or "",
                    row.branch or "",
                    # `needs_review` defaults to false in the ledger: blank until classified
                    "" if row.format is None else str(bool(row.needs_review)).lower(),
                    row.review_reason or "",
                    folder,
                ]
            )
        data = buffer.getvalue().encode("utf-8", errors="surrogateescape")
        path.parent.mkdir(parents=True, exist_ok=True)
        attempt = 0
        while True:
            path = report_path(results_root, stamp, attempt)
            try:
                handle = path.open("xb")
            except FileExistsError:
                attempt += 1
                continue
            break
        with handle:
            handle.write(data)
    except (OSError, UnicodeError):
        failed = True
    if failed:
        raise ReportWriteError(REPORT_WRITE_FAILED)
    return path
