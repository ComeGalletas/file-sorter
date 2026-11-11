"""API-001.1: the read model behind every route, the UI (.4) and the report (.5).

Every view is a pydantic model with an explicit field allowlist (`extra="forbid"`). A file
row is built from a `select` that names only the allowlisted columns, so `source_path`,
`duplicate_paths` and the raw name are never even loaded (ING-001.D2, DOC-007.D1, m4
privacy item 11). Fields that hold a name (the sanitized name, a category name) are
`repr=False`, so a logged view never shows one (m3 privacy item 4).
"""

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Connection, Select, and_, func, select, true

from classifier.db.models import File, FileStatus, Run

PER_PAGE = 50  # API-001.D5
CROSS_CHECK_REASON = "nsfw_disagreement"  # CLS-004.D5, D13
NOT_AVAILABLE = "n/a"  # m4 answer 7
# API-001.D8 (corrected): the ledger's adult branch is classify_rules' "nsfw" (R-CLS-1).
# Pinned to branch_for_level by tests/unit/api/test_views.py; use is_adult, never the literal.
ADULT_BRANCH = "nsfw"

# The contract's 15 fields (docs/plans/m4.md, "Contracts fixed here"). Nothing else.
FILE_ROW_FIELDS = (
    "source_hash",
    "short_hash",
    "sanitized_name",
    "ext",
    "status",
    "branch",
    "format",
    "topic",
    "nsfw_level",
    "nsfw_traces",
    "cross_check_disagrees",
    "needs_review",
    "review_reason",
    "error",
    "updated_at",
    "blurred",  # API-001.3: the 16th field, from is_adult (API-001.D8)
)

# The only ledger columns the API ever reads for a row.
_ROW_COLUMNS = (
    File.source_hash,
    File.short_hash,
    File.original_sanitized,
    File.ext,
    File.status,
    File.branch,
    File.format,
    File.topic,
    File.nsfw_level,
    File.nsfw_traces,
    File.needs_review,
    File.review_reason,
    File.error,
    File.updated_at,
)


class _View(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class FileRow(_View):
    source_hash: str
    short_hash: str
    sanitized_name: str | None = Field(repr=False)  # null before sanitize (lead, #210)
    ext: str
    status: str
    branch: str | None
    format: str | None = Field(repr=False)  # a category name
    topic: str | None = Field(repr=False)  # a category name; null = no topic
    nsfw_level: str | None
    nsfw_traces: bool | None
    cross_check_disagrees: bool
    needs_review: bool
    review_reason: str | None
    error: str | None  # a fixed error code
    updated_at: datetime
    blurred: bool  # is_adult(branch); the UI blurs it by default (m4 answer 3, API-001.D8)


class FilePage(_View):
    page: int
    per_page: int
    total: int
    rows: list[FileRow]


class RunView(_View):
    """The newest `runs` row. Its `counts` and `error` are closed sets (DB-007.D3)."""

    id: int
    kind: str
    state: str
    started_at: datetime
    finished_at: datetime | None
    counts: dict[str, dict[str, int | float]]  # {node: {field: number}}
    error: str | None  # one of RUN_ERRORS


def is_adult(branch: str | None) -> bool:
    """True only for the classify rules' adult branch (API-001.D8); safe and null are not."""
    return branch == ADULT_BRANCH


class GridCell(_View):
    topic: str | None = Field(repr=False)
    format: str | None = Field(repr=False)
    branch: str | None
    adult: bool  # the safe-vs-adult split, from is_adult (API-001.D8)
    count: int


class ModelView(_View):
    name: str
    size_vram: int  # bytes


class LastError(_View):
    short_hash: str
    status: str
    error: str  # a fixed error code
    updated_at: datetime


class StatusView(_View):
    run: RunView | None  # null until a run is recorded (API-001.1.4)
    imgs_per_min: float | None  # API-001.D7; null with no run
    counts_by_status: dict[str, int]
    grid: list[GridCell]  # topic x format x branch
    loaded_models: list[ModelView] | Literal["n/a"]
    last_error: LastError | None


class FileFilters(_View):
    status: FileStatus | None = None
    format: str | None = Field(default=None, repr=False)
    topic: str | None = Field(default=None, repr=False)
    needs_review: bool | None = None


class LoadedModelLike(Protocol):
    """MOD-003.1's `LoadedModel`, structurally: `name` and `size_vram` (bytes)."""

    name: str
    size_vram: int


class ModelProbe(Protocol):
    """MOD-003.1's `OllamaClient.loaded_models()`: `None` on any failure."""

    def loaded_models(self) -> list[LoadedModelLike] | None: ...


def _sanitized_name(stem: str | None, ext: str) -> str | None:
    if stem is None:
        return None
    return f"{stem}.{ext}" if ext else stem


def file_row(m: Mapping[str, Any]) -> FileRow:
    """A row from one result mapping of `_ROW_COLUMNS`."""
    status = m["status"]
    return FileRow(
        source_hash=m["source_hash"],
        short_hash=m["short_hash"],
        sanitized_name=_sanitized_name(m["original_sanitized"], m["ext"]),
        ext=m["ext"],
        status=status.value if isinstance(status, FileStatus) else str(status),
        branch=m["branch"],
        format=m["format"],
        topic=m["topic"],
        nsfw_level=m["nsfw_level"],
        nsfw_traces=m["nsfw_traces"],
        cross_check_disagrees=m["review_reason"] == CROSS_CHECK_REASON,
        blurred=is_adult(m["branch"]),
        needs_review=bool(m["needs_review"]),
        review_reason=m["review_reason"],
        error=m["error"],
        updated_at=m["updated_at"],
    )


def _where(filters: FileFilters) -> list[Any]:
    clauses: list[Any] = []
    if filters.status is not None:
        clauses.append(File.status == filters.status)
    if filters.format is not None:
        clauses.append(File.format == filters.format)
    if filters.topic is not None:
        clauses.append(File.topic == filters.topic)
    if filters.needs_review is not None:
        clauses.append(File.needs_review.is_(filters.needs_review))
    return clauses


def rows_query(filters: FileFilters) -> Select[Any]:
    """Allowlisted columns, the filters ANDed, newest first (API-001.D5)."""
    return (
        select(*_ROW_COLUMNS)
        .where(and_(true(), *_where(filters)))
        .order_by(File.updated_at.desc(), File.source_hash)
    )


def build_file_page(conn: Connection, filters: FileFilters, page: int) -> FilePage:
    total = conn.execute(
        select(func.count()).select_from(File).where(and_(true(), *_where(filters)))
    ).scalar_one()
    result = conn.execute(rows_query(filters).limit(PER_PAGE).offset((page - 1) * PER_PAGE))
    rows = [file_row(m) for m in result.mappings()]
    return FilePage(page=page, per_page=PER_PAGE, total=total, rows=rows)


def _counts_by_status(conn: Connection) -> dict[str, int]:
    counts = {s.value: 0 for s in FileStatus}
    for status, n in conn.execute(select(File.status, func.count()).group_by(File.status)):
        counts[status.value] = n
    return counts


def _grid(conn: Connection) -> list[GridCell]:
    query = (
        select(File.topic, File.format, File.branch, func.count())
        .group_by(File.topic, File.format, File.branch)
        .order_by(File.topic, File.format, File.branch)
    )
    return [
        GridCell(topic=t, format=f, branch=b, adult=is_adult(b), count=n)
        for t, f, b, n in conn.execute(query)
    ]


def _last_error(conn: Connection) -> LastError | None:
    query = (
        select(File.short_hash, File.status, File.error, File.updated_at)
        .where(File.error.is_not(None))
        .order_by(File.updated_at.desc(), File.source_hash)
        .limit(1)
    )
    m = conn.execute(query).mappings().first()
    if m is None:
        return None
    return LastError(
        short_hash=m["short_hash"],
        status=m["status"].value,
        error=m["error"],
        updated_at=m["updated_at"],
    )


def loaded_models_view(probe: ModelProbe | None) -> list[ModelView] | Literal["n/a"]:
    """The loaded models, or "n/a" when Ollama can't tell (m4 answer 7, MOD-003.1)."""
    if probe is None:
        return NOT_AVAILABLE
    views: list[ModelView] | None = None
    try:
        models = probe.loaded_models()
        if models is not None:
            views = [ModelView(name=m.name, size_vram=m.size_vram) for m in models]
    except Exception:  # the contract says it never raises; be safe, keep no text
        views = None
    return NOT_AVAILABLE if views is None else views


def _latest_run(conn: Connection) -> tuple[RunView, datetime] | None:
    """The newest run, and the database's `now()` (the end of a running run's window)."""
    query = (
        select(
            Run.id,
            Run.kind,
            Run.state,
            Run.started_at,
            Run.finished_at,
            Run.counts,
            Run.error,
            func.now().label("now"),
        )
        .order_by(Run.started_at.desc(), Run.id.desc())
        .limit(1)
    )
    m = conn.execute(query).mappings().first()
    if m is None:
        return None
    run = RunView(
        id=m["id"],
        kind=m["kind"],
        state=m["state"],
        started_at=m["started_at"],
        finished_at=m["finished_at"],
        counts=m["counts"],
        error=m["error"],
    )
    return run, m["now"]


def _imgs_per_min(conn: Connection, run: RunView, now: datetime) -> float | None:
    """API-001.D7: rows with `updated_at` in the run's window, per elapsed minute.

    The window ends at `finished_at`, or at `now` while the run is running. An empty or
    negative window gives None.
    """
    end = run.finished_at if run.finished_at is not None else now
    minutes = (end - run.started_at).total_seconds() / 60
    if minutes <= 0:
        return None
    moved = conn.execute(
        select(func.count())
        .select_from(File)
        .where(File.updated_at >= run.started_at, File.updated_at <= end)
    ).scalar_one()
    return moved / minutes


def build_status(conn: Connection, *, now: datetime | None = None) -> StatusView:
    """The database part of the status; `loaded_models` is "n/a" until
    `with_loaded_models` fills it, after the connection is closed (round 1, item 4).

    `now` overrides the database clock for a running run's window (tests only).
    """
    latest = _latest_run(conn)
    run = latest[0] if latest else None
    rate = None
    if latest is not None:
        rate = _imgs_per_min(conn, latest[0], now if now is not None else latest[1])
    return StatusView(
        run=run,
        imgs_per_min=rate,
        counts_by_status=_counts_by_status(conn),
        grid=_grid(conn),
        loaded_models=NOT_AVAILABLE,
        last_error=_last_error(conn),
    )


def with_loaded_models(status: StatusView, probe: ModelProbe | None) -> StatusView:
    """`status` with the loaded models from Ollama; call it with no connection held."""
    return status.model_copy(update={"loaded_models": loaded_models_view(probe)})
