"""The sanitize node: `queued` → `sanitized`, one file at a time, all or nothing (SAN-001.4).

Per file (SAN-001.D9): the name is redacted first (literal → regex → entity, R-SAN-4), then
the working copy is made in `.work/` with the metadata strip as its transform (FOP-001.D1),
then the thumbnail (ING-002), then, in one savepoint, the `sanitize_log` rows, the sanitized
stem and the status. Any exception sets `error` with a fixed reason (SAN-001.D2, D16, D17):
an unredacted name never moves on, and the next run retries the file (R-ING-2).

The node never commits; `run` commits once per node (PIPE-001.D3). It never writes under
`source_root` (P-1): the work folders and every published file are checked by their
resolved path (SAN-001.D16). Logs carry short hashes, counts, fixed reasons and exception
type names only, never a path, a name, a tag or `str(exc)` (DOC-007.D1). No model sees the
source path: the entity rule gets only the segment and stem text left after the literal and
regex rules, and later nodes read `files.original_sanitized`.
"""

import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import TYPE_CHECKING

import httpx
import psycopg

from classifier.config import Config
from classifier.fileops.copy_move import make_working_copy
from classifier.fileops.thumbs import make_thumbnail
from classifier.models.ollama import OllamaClient
from classifier.sanitize.entity import EntityUnavailableError, check_backend, entity_detector
from classifier.sanitize.exif import MetadataStripError, strip_metadata
from classifier.sanitize.rules import (
    EntityFn,
    EntityRule,
    Redaction,
    Rules,
    SanitizeConfigError,
    load_rules,
    sanitize_name,
)

if TYPE_CHECKING:
    from classifier.graph.nodes import NodeContext

log = logging.getLogger(__name__)

WORK_DIR = ".work"  # R-FOP-1: under results_root
THUMBS_DIR = "thumbs"  # ING-002.D1: .work/thumbs/<source_hash>.webp

# SAN-001.D17: the fixed reasons a file's `files.error` can hold after this node.
ENTITY_UNAVAILABLE = EntityUnavailableError.reason  # D2: "sanitize_entity_unavailable"
METADATA_RESIDUAL = MetadataStripError.reason  # D2: "sanitize_metadata_residual"
NAME_FAILED = "sanitize_name_failed"
WORKING_COPY_FAILED = "sanitize_working_copy_failed"
PATH_ESCAPE = "sanitize_path_escape"
THUMBNAIL_FAILED = "sanitize_thumbnail_failed"
LEDGER_REJECTED = "sanitize_ledger_rejected"
REASONS = (
    ENTITY_UNAVAILABLE,
    METADATA_RESIDUAL,
    NAME_FAILED,
    WORKING_COPY_FAILED,
    PATH_ESCAPE,
    THUMBNAIL_FAILED,
    LEDGER_REJECTED,
)

_QUEUED = """
select source_hash, short_hash, source_path, ext
  from files
 where status = 'queued'
 order by created_at, source_hash
"""

# SAN-001.D18: the log describes the current working copy, so a retry replaces the rows.
_CLEAR_LOG = "delete from sanitize_log where source_hash = %s"
_INSERT_LOG = """
insert into sanitize_log (source_hash, rule_id, field, before_hash, after_value)
values (%s, %s, %s, %s, %s)
"""
_SANITIZED = """
update files
   set status = 'sanitized', original_sanitized = %s, error = null, updated_at = now()
 where source_hash = %s and status = 'queued'
"""
# PIPE-001.D2: the node overwrites its own column on failure too.
_ERROR = """
update files
   set status = 'error', error = %s, original_sanitized = null, updated_at = now()
 where source_hash = %s and status = 'queued'
"""


class WorkDirError(Exception):
    """`.work/` would resolve outside `results_root` or into `source_root` (SAN-001.D16).

    Fixed text only: never a path.
    """


@dataclass(frozen=True)
class SanitizeResult:
    """What one sanitize run did: counts and fixed reasons only (CLI-003 prints them)."""

    sanitized: int = 0
    errored: int = 0
    by_reason: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def total(self) -> int:
        return self.sanitized + self.errored


class _FileFailed(Exception):
    """One file failed: carries the fixed reason and the type name of what was raised."""

    def __init__(self, reason: str, kind: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.kind = kind


@dataclass(frozen=True)
class _Row:
    source_hash: str
    short_hash: str
    source_path: str = field(repr=False)  # DOC-004.D3: never logged
    ext: str


@dataclass(frozen=True)
class _Folders:
    """The resolved roots and work folders, checked once before any file is written."""

    source: Path = field(repr=False)
    work: Path = field(repr=False)
    thumbs: Path = field(repr=False)


def check_settings(config: Config) -> None:
    """Fail fast on settings M2 doesn't support, naming the key only (SAN-001.D6)."""
    if config.sanitizer.ocr:
        raise SanitizeConfigError("sanitizer.ocr: true is not supported in M2; set it to false")
    check_backend(config)  # SAN-001.3's rule, checked even when no entity rule is configured


def entity_client(rules: Rules, transport: httpx.BaseTransport | None) -> OllamaClient | None:
    """An Ollama client when an `entity` rule needs one, else None: no rule, no call."""
    if not rules.of_type(EntityRule):
        return None
    return OllamaClient.from_env(transport=transport)  # OLLAMA_HOST, the compose service only


def _under(path: Path, root: Path) -> bool:
    return path == root or path.is_relative_to(root)


def prepare_folders(source_root: Path, results_root: Path) -> _Folders:
    """Resolve, check, create and re-check `.work/` and `.work/thumbs/` (SAN-001.D16).

    Checked before anything is created, so a symlinked results folder or `.work` can't
    redirect even the `mkdir` into the source; and again after, on the real folders.
    """
    source = source_root.resolve()

    def check() -> tuple[Path, Path]:
        results = results_root.resolve()
        work = (results_root / WORK_DIR).resolve()
        thumbs = (results_root / WORK_DIR / THUMBS_DIR).resolve()
        if work != results / WORK_DIR or thumbs != work / THUMBS_DIR:
            raise WorkDirError("results_root/.work must be a real folder, not a link elsewhere")
        if _under(results, source) or _under(source, results):
            raise WorkDirError("results_root and source_root must not overlap (R-FOP-9)")
        return work, thumbs

    check()
    (results_root / WORK_DIR / THUMBS_DIR).mkdir(parents=True, exist_ok=True)
    work, thumbs = check()
    return _Folders(source=source, work=work, thumbs=thumbs)


def _published(path: Path, folder: Path, name: str, folders: _Folders) -> None:
    """The file just published must really sit at `folder/name` (SAN-001.D16)."""
    try:
        real = path.resolve(strict=True)
        ok = real == folder / name and not _under(real, folders.source) and not path.is_symlink()
    except (OSError, RuntimeError):
        ok = False
    if not ok:
        raise _FileFailed(PATH_ESCAPE, "PathEscape")


def _attempt[T](
    reason: str, step: Callable[[], T], by_type: Mapping[type[Exception], str] | None = None
) -> T:
    """Run one step; any exception becomes `_FileFailed` with a fixed reason (SAN-001.D16).

    `by_type` maps an exception class to a more specific reason. The original exception is
    not chained, and only its type name is kept: its message may hold a path, a name or a
    tag value.
    """
    failure = None
    try:
        return step()
    except Exception as exc:  # SAN-001.D16: every exception fails the file
        specific = [r for cls, r in (by_type or {}).items() if isinstance(exc, cls)]
        failure = _FileFailed(specific[0] if specific else reason, type(exc).__name__)
    raise failure


def _sanitize_one(
    conn: psycopg.Connection,
    row: _Row,
    source_root: Path,
    folders: _Folders,
    rules: Rules,
    entity: EntityFn | None,
    thumb_size: int,
) -> None:
    def relative() -> PurePosixPath:
        return PurePosixPath(row.source_path).relative_to(PurePosixPath(source_root))

    path = _attempt(NAME_FAILED, relative)
    name = _attempt(
        NAME_FAILED,
        lambda: sanitize_name(path, rules, entity),
        {EntityUnavailableError: ENTITY_UNAVAILABLE},
    )

    stripped: list[Redaction] = []

    def transform(tmp: Path) -> None:
        stripped[:] = strip_metadata(tmp, rules)

    copy = _attempt(
        WORKING_COPY_FAILED,
        partial(
            make_working_copy, Path(row.source_path), folders.work, row.source_hash, row.ext,
            transform,
        ),
        {MetadataStripError: METADATA_RESIDUAL},
    )  # fmt: skip
    _published(copy.path, folders.work, f"{row.source_hash}.{row.ext}", folders)

    thumb = _attempt(
        THUMBNAIL_FAILED,
        partial(make_thumbnail, copy.path, folders.thumbs, row.source_hash, thumb_size),
    )
    _published(thumb, folders.thumbs, f"{row.source_hash}.webp", folders)

    def record() -> None:
        with conn.transaction():  # a savepoint: run's transaction is already open
            conn.execute(_CLEAR_LOG, (row.source_hash,))
            redactions = [*name.redactions, *stripped]
            if redactions:
                with conn.cursor() as cursor:
                    cursor.executemany(
                        _INSERT_LOG,
                        [
                            (row.source_hash, r.rule_id, r.field, r.before_hash, r.after_value)
                            for r in redactions
                        ],
                    )
            if conn.execute(_SANITIZED, (name.stem, row.source_hash)).rowcount != 1:
                raise LookupError("the row is no longer queued")

    _attempt(LEDGER_REJECTED, record)


def sanitize(conn: psycopg.Connection, ctx: "NodeContext") -> SanitizeResult:
    """Sanitize every `queued` row (R-SAN-1 to R-SAN-4, R-SAN-6, R-ING-5, P-4).

    Settings, the rules file, the log key, the entity client and the work folders are
    checked before any file is touched; a failure there raises, and `run` rolls the node
    back. After that, a failing file never stops the batch.
    """
    if conn.autocommit:
        raise ValueError("the sanitize node needs run's transaction (PIPE-001.D3)")
    config = ctx.config
    check_settings(config)
    rules = load_rules(config.sanitizer.rules_file)
    rows = [_Row(*map(str, found)) for found in conn.execute(_QUEUED).fetchall()]
    if not rows:  # a re-run: nothing queued, nothing touched (P-4)
        log.info("sanitize: 0 sanitized, 0 error")
        return SanitizeResult()
    client = entity_client(rules, ctx.ollama_transport)
    try:
        # Built only through SAN-001.3's factory, which runs check_backend (SAN-001.D6).
        entity = None if client is None else entity_detector(config, client)
        folders = prepare_folders(ctx.source_root, ctx.results_root)
        return _batch(conn, rows, ctx.source_root, folders, rules, entity, config.thumbs.size)
    finally:
        if client is not None:
            client.close()


def _batch(
    conn: psycopg.Connection,
    rows: list[_Row],
    source_root: Path,
    folders: _Folders,
    rules: Rules,
    entity: EntityFn | None,
    thumb_size: int,
) -> SanitizeResult:
    sanitized = 0
    reasons: Counter[str] = Counter()
    for row in rows:
        try:
            _sanitize_one(conn, row, source_root, folders, rules, entity, thumb_size)
        except _FileFailed as failed:
            conn.execute(_ERROR, (failed.reason, row.source_hash))
            reasons[failed.reason] += 1
            log.warning("sanitize: %s error %s (%s)", row.short_hash, failed.reason, failed.kind)
            continue
        sanitized += 1
    result = SanitizeResult(
        sanitized, sum(reasons.values()), MappingProxyType(dict(sorted(reasons.items())))
    )
    log.info("sanitize: %d sanitized, %d error", result.sanitized, result.errored)
    return result
