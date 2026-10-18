"""The classify node: `sanitized` → `classified` (CLS-004.4, R-CLS-0 to R-CLS-6, R-PIPE-1, P-2).

The node reads only the sanitized working copy `<results_root>/.work/<source_hash>.<ext>`,
a path built from the hash and the extension, never from `source_path` (CLS-002.D8, P-2).
Models get decoded pixels only, through `classifier/models/`; the one name a model may see is
`files.original_sanitized`, as a hint to the classify call (CLS-004.D6). SigLIP still produces
`image_vec` and Falconsai a cross-check score; the VLM decides format, topic and NSFW level
(CLS-004.D1 to D7). It never writes a file and never commits; `run` commits once per node
(PIPE-001.D3).

Logs carry short hashes, counts and fixed reasons only (DOC-007.D1). Errors are fixed text,
raised outside the `except` block so `__cause__` and `__context__` stay None.
"""

import io
import logging
import math
import os
import stat
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING

import numpy as np
import psycopg
from PIL import Image

from classifier.config import Config
from classifier.fileops.copy_move import working_copy_name
from classifier.graph.errors import mark_error, register_reasons
from classifier.graph.sanitize import check_work_dir
from classifier.models.classify_rules import CategoryRule, decide, validate_rules
from classifier.models.ollama import OllamaClient
from classifier.models.siglip import BATCH_SIZE, SiglipBackend
from classifier.models.vision import VisionBackend, VisionError
from classifier.models.vlm_classify import UNANSWERED_REASON, vlm_classify

if TYPE_CHECKING:
    from classifier.graph.nodes import NodeContext

log = logging.getLogger(__name__)

WORKING_COPY_UNREADABLE = "classify_working_copy_unreadable"  # CLS-002.D7
LEDGER_WRITE_FAILED = "classify_ledger_write_failed"  # CLS-002.2.5
VLM_UNANSWERED = UNANSWERED_REASON  # CLS-004.D4: "classify_vlm_unanswered"
register_reasons(
    (WORKING_COPY_UNREADABLE, LEDGER_WRITE_FAILED, VLM_UNANSWERED)
)  # SAN-003.D2: mark_error stores only fixed reasons

IMAGE_VEC_DIM = 1152  # files.image_vec is vector(1152), migration 0003 (CLS-002.D10)
_SANITIZED = "sanitized"
_BAD_SHAPE = "the vision backend returned embeddings of an unexpected shape"
_SEPARATE_UNSUPPORTED = "nsfw.mode: separate is not supported in M3; set it to mirror"


class ClassifyConfigError(Exception):
    """A setting or table M3 can't work with. Names the key only, never a value (CLS-002.D9)."""


class WorkingCopyUnreadable(Exception):
    """One working copy is missing, linked, not a regular file or not decodable (CLS-002.D7).

    Fixed text only: the library and OS messages carry the path, so they are dropped.
    """

    reason = WORKING_COPY_UNREADABLE

    def __init__(self) -> None:
        super().__init__(WORKING_COPY_UNREADABLE)


@dataclass(frozen=True)
class ClassifyResult:
    """What one classify run did: counts and fixed reasons only (CLI-005 and gate 3 read them).

    `classified` counts every row that reached `classified`; `unsorted`, `no_topic` and
    `adult` are subsets of it. `errored` rows are not in `classified`.
    """

    classified: int = 0
    unsorted: int = 0
    no_topic: int = 0
    adult: int = 0
    errored: int = 0
    by_reason: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def total(self) -> int:
        return self.classified + self.errored


def check_settings(config: Config) -> None:
    """Fail fast on settings M3 doesn't support, naming the key only (CLS-002.D9)."""
    if config.nsfw.mode != "mirror":
        raise ClassifyConfigError(_SEPARATE_UNSUPPORTED)


def open_working_frames(work: Path, source_hash: str, ext: str) -> Image.Image:
    """Read one working copy once and return it undecoded past frame 0, seekable (CLS-004.4).

    The name comes from `working_copy_name`, the helper sanitize publishes through. The file
    is opened with `O_NOFOLLOW` (a link is refused) and `O_NONBLOCK` (a pipe can't hang the
    run), and must be a regular file by `fstat` on the open descriptor. The bytes are read
    into memory, so the image keeps every frame after the descriptor closes and the VLM client
    can seek them itself. Frame 0 is decoded here, so a corrupt file fails now. Any failure
    raises `WorkingCopyUnreadable`, unchained.
    """
    image: Image.Image | None = None
    try:
        path = work / working_copy_name(source_hash, ext)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            handle = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError("not a regular file")
            data = handle.read()
        image = Image.open(io.BytesIO(data))
        image.load()  # frame 0 decodes now
    except Exception:
        image = None
    if image is None:
        raise WorkingCopyUnreadable
    return image


def first_frame_rgb(image: Image.Image) -> Image.Image:
    """Frame 0 of an opened working copy as RGB, for SigLIP and Falconsai (R-ING-6, CLS-002.D8).

    Derived from the same in-memory image the VLM client gets, so a file is read once. Leaves
    `image` positioned on frame 0. Any failure raises `WorkingCopyUnreadable`, unchained.
    """
    frame: Image.Image | None = None
    try:
        image.seek(0)
        frame = image.convert("RGB")
    except Exception:
        frame = None
    if frame is None:
        raise WorkingCopyUnreadable
    return frame


def open_working_copy(work: Path, source_hash: str, ext: str) -> Image.Image:
    """The first frame of one working copy as RGB (R-ING-6, CLS-002.D8)."""
    with open_working_frames(work, source_hash, ext) as image:
        return first_frame_rgb(image)


_ROWS = """
select source_hash, short_hash, ext, original_sanitized
  from files
 where status = 'sanitized'
 order by created_at, source_hash
"""
_RULES = """
select id, axis, name, folder, min_score, branch, parent_id
  from categories
 order by id
"""
_CLASSIFIED = """
update files
   set status = 'classified', branch = %s, nsfw_score = %s, nsfw_level = %s, format = %s,
       topic = %s, format_scores = null, topic_scores = null, needs_review = %s,
       review_reason = %s, image_vec = %s::vector, error = null, updated_at = now()
 where source_hash = %s and status = 'sanitized'
"""


@dataclass(frozen=True)
class _Row:
    source_hash: str
    short_hash: str
    ext: str
    hint: str | None = field(repr=False)  # `original_sanitized`: the only name a model may see


def _load_rules(conn: psycopg.Connection) -> list[CategoryRule]:
    return [
        CategoryRule(
            id=int(i),
            axis=str(axis),
            name=str(name),
            folder=str(folder),
            min_score=None if min_score is None else float(min_score),
            branch=str(branch),
            parent_id=None if parent is None else int(parent),
        )
        for i, axis, name, folder, min_score, branch, parent in conn.execute(_RULES).fetchall()
    ]


def _backend(ctx: "NodeContext") -> VisionBackend:
    if ctx.vision is not None:
        return ctx.vision
    return SiglipBackend(ctx.config.models.classifier, ctx.config.models.nsfw)


def _vector_literal(vector: np.ndarray) -> str:
    return "[" + ",".join(repr(float(x)) for x in vector.tolist()) + "]"


def classify(conn: psycopg.Connection, ctx: "NodeContext") -> ClassifyResult:
    """Classify every `sanitized` row (R-CLS-0 to R-CLS-6, R-PIPE-1, P-2, P-4).

    The settings, the rules and the work folder are checked before any row changes; a
    failure there raises and `run` rolls the node back. So does a model that can't load
    (CLS-002.D7) or Ollama being unreachable (CLS-004.D4). After that a file with an unreadable
    working copy goes to `error` and the batch goes on. A re-run finds no `sanitized` row and
    touches nothing.
    """
    if conn.autocommit:
        raise ValueError("the classify node needs run's transaction (PIPE-001.D3)")
    config = ctx.config
    check_settings(config)
    rows = [
        _Row(str(h), str(short), str(ext), None if hint is None else str(hint))
        for h, short, ext, hint in conn.execute(_ROWS).fetchall()
    ]
    if not rows:  # a re-run: nothing sanitized, nothing touched (P-4)
        log.info("classify: 0 classified, 0 error")
        return ClassifyResult()
    rules = _load_rules(conn)
    validate_rules(rules, None)  # CLS-002.D4, CLS-004.D7: refuses before any row changes
    work = check_work_dir(ctx.source_root, ctx.results_root)
    backend = _backend(ctx)
    # One client for the whole node: ollama_transport is the test seam, as in sanitize.
    with OllamaClient.from_env(transport=ctx.ollama_transport) as client:
        return _batches(conn, rows, work, rules, backend, client, config)


def _open(work: Path, row: _Row) -> tuple[Image.Image, Image.Image] | None:
    """The working copy once: every frame for the VLM, the first frame as RGB for SigLIP."""
    try:
        frames = open_working_frames(work, row.source_hash, row.ext)
        return frames, first_frame_rgb(frames)
    except WorkingCopyUnreadable:
        return None


def _batches(
    conn: psycopg.Connection,
    rows: Sequence[_Row],
    work: Path,
    rules: Sequence[CategoryRule],
    backend: VisionBackend,
    client: OllamaClient,
    config: Config,
) -> ClassifyResult:
    formats = [r.name for r in rules if r.axis == "format"]
    topics = [r.name for r in rules if r.axis == "topic"]
    classified = unsorted = no_topic = adult = 0
    reasons: Counter[str] = Counter()
    for start in range(0, len(rows), BATCH_SIZE):  # bounds the decoded pixels held at once
        opened: list[tuple[_Row, Image.Image, Image.Image]] = []
        for row in rows[start : start + BATCH_SIZE]:
            both = _open(work, row)
            if both is None:
                mark_error(
                    conn, row.source_hash, WORKING_COPY_UNREADABLE, from_statuses=(_SANITIZED,)
                )
                reasons[WORKING_COPY_UNREADABLE] += 1
                log.warning("classify: %s error %s", row.short_hash, WORKING_COPY_UNREADABLE)
                continue
            opened.append((row, *both))
        if not opened:
            continue
        rgb = [first for _, _, first in opened]
        vectors = np.asarray(backend.embed_images(rgb), dtype=np.float32)
        nsfw = np.asarray(backend.nsfw_scores(rgb), dtype=np.float64)
        if vectors.shape != (len(rgb), IMAGE_VEC_DIM) or nsfw.shape != (len(rgb),):
            raise VisionError(_BAD_SHAPE)
        for (row, frames, _), vector, nsfw_score in zip(opened, vectors, nsfw, strict=True):
            score = float(nsfw_score) if math.isfinite(float(nsfw_score)) else None
            answer = vlm_classify(
                client,
                config.models.vlm_safe,
                frames,
                hint=row.hint,
                formats=formats,
                topics=topics,
            )
            choice = decide(answer, rules, score, config.nsfw)
            write = (
                choice.branch,
                score,
                answer.level.name,
                choice.format,
                choice.topic,
                choice.needs_review,
                choice.review_reason,
                _vector_literal(vector),
                row.source_hash,
            )
            moved = 0
            rejected = False
            try:
                with conn.transaction():  # a savepoint: one bad row can't undo the others
                    moved = conn.execute(_CLASSIFIED, write).rowcount
            except psycopg.Error:
                rejected = True  # acted on below, outside the handler; the text may hold values
            if rejected:
                mark_error(conn, row.source_hash, LEDGER_WRITE_FAILED, from_statuses=(_SANITIZED,))
                reasons[LEDGER_WRITE_FAILED] += 1
                log.warning("classify: %s error %s", row.short_hash, LEDGER_WRITE_FAILED)
                continue
            if moved != 1:  # no longer `sanitized`: another run got there first
                continue
            classified += 1
            unsorted += choice.format == "unsorted"
            no_topic += choice.topic is None
            adult += choice.branch == "nsfw"
    result = ClassifyResult(
        classified,
        unsorted,
        no_topic,
        adult,
        sum(reasons.values()),
        MappingProxyType(dict(sorted(reasons.items()))),
    )
    log.info(
        "classify: %d classified, %d unsorted, %d no topic, %d adult, %d error",
        result.classified,
        result.unsorted,
        result.no_topic,
        result.adult,
        result.errored,
    )
    return result
