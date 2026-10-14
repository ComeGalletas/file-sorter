"""The classify node: `sanitized` → `classified` (CLS-002.2, R-CLS-0 to R-CLS-6, R-PIPE-1, P-2).

The node reads only the sanitized working copy `<results_root>/.work/<source_hash>.<ext>`,
a path built from the hash and the extension, never from `source_path` (CLS-002.D8, P-2).
Models get decoded pixels only, through `classifier/models/`. It never writes a file and
never commits; `run` commits once per node (PIPE-001.D3).

Logs carry short hashes, counts and fixed reasons only (DOC-007.D1). Errors are fixed text,
raised outside the `except` block so `__cause__` and `__context__` stay None.
"""

import logging
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
from psycopg.types.json import Jsonb

from classifier.config import Config
from classifier.fileops.copy_move import working_copy_name
from classifier.graph.errors import mark_error, register_reasons
from classifier.graph.sanitize import check_work_dir
from classifier.models.classify_rules import CategoryRule, choose, nsfw_branch, validate_rules
from classifier.models.siglip import BATCH_SIZE, SiglipBackend
from classifier.models.vision import (
    VisionBackend,
    VisionError,
    cosine_matrix,
    max_over_prompts,
    score_matrix,
)

if TYPE_CHECKING:
    from classifier.graph.nodes import NodeContext

log = logging.getLogger(__name__)

WORKING_COPY_UNREADABLE = "classify_working_copy_unreadable"  # CLS-002.D7
register_reasons((WORKING_COPY_UNREADABLE,))  # SAN-003.D2: mark_error stores only fixed reasons

IMAGE_VEC_DIM = 1152  # files.image_vec is vector(1152), migration 0003 (CLS-002.D10)
_SANITIZED = "sanitized"
_NO_PROMPTS = "no category has a prompt to score against; check the categories tables"
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


def open_working_copy(work: Path, source_hash: str, ext: str) -> Image.Image:
    """Decode the first frame of one working copy as RGB (R-ING-6, CLS-002.D8).

    The name comes from `working_copy_name`, the helper sanitize publishes through. The file
    is opened with `O_NOFOLLOW` (a link is refused) and `O_NONBLOCK` (a pipe can't hang the
    run), and must be a regular file by `fstat` on the open descriptor. Any failure raises
    `WorkingCopyUnreadable`, unchained.
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
            with Image.open(handle) as opened:
                opened.seek(0)  # R-ING-6: the first frame only
                image = opened.convert("RGB")  # loads the pixels before the file closes
    except Exception:
        image = None
    if image is None:
        raise WorkingCopyUnreadable
    return image


_ROWS = """
select source_hash, short_hash, ext
  from files
 where status = 'sanitized'
 order by created_at, source_hash
"""
_RULES = """
select id, axis, name, folder, min_score, branch, parent_id
  from categories
 order by id
"""
_PROMPTS = "select category_id, prompt from category_prompts order by category_id, position"
_CLASSIFIED = """
update files
   set status = 'classified', branch = %s, nsfw_score = %s, format = %s, topic = %s,
       format_scores = %s, topic_scores = %s, needs_review = %s, review_reason = %s,
       image_vec = %s::vector, error = null, updated_at = now()
 where source_hash = %s and status = 'sanitized'
"""


@dataclass(frozen=True)
class _Row:
    source_hash: str
    short_hash: str
    ext: str


@dataclass(frozen=True)
class _Prompts:
    """Every prompt in `category_prompts`, with the id of the category it belongs to."""

    texts: list[str] = field(repr=False)
    category_ids: list[str] = field(repr=False)  # str(id): a name can repeat across the axes


def _load_categories(conn: psycopg.Connection) -> tuple[list[CategoryRule], _Prompts]:
    rules = [
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
    found = conn.execute(_PROMPTS).fetchall()
    return rules, _Prompts([str(p) for _, p in found], [str(c) for c, _ in found])


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
    (CLS-002.D7). After that a file with an unreadable working copy goes to `error` and the
    batch goes on. A re-run finds no `sanitized` row and touches nothing.
    """
    if conn.autocommit:
        raise ValueError("the classify node needs run's transaction (PIPE-001.D3)")
    config = ctx.config
    check_settings(config)
    rows = [_Row(*map(str, found)) for found in conn.execute(_ROWS).fetchall()]
    if not rows:  # a re-run: nothing sanitized, nothing touched (P-4)
        log.info("classify: 0 classified, 0 error")
        return ClassifyResult()
    rules, prompts = _load_categories(conn)
    validate_rules(rules, config.classify)  # CLS-002.D4: refuses before any row changes
    if not prompts.texts:
        raise ClassifyConfigError(_NO_PROMPTS)
    work = check_work_dir(ctx.source_root, ctx.results_root)
    backend = _backend(ctx)
    text_vectors = backend.embed_texts(prompts.texts)  # CLS-002.D11: encoded once per call
    return _batches(conn, rows, work, rules, prompts, backend, text_vectors, config)


def _batches(
    conn: psycopg.Connection,
    rows: Sequence[_Row],
    work: Path,
    rules: Sequence[CategoryRule],
    prompts: _Prompts,
    backend: VisionBackend,
    text_vectors: np.ndarray,
    config: Config,
) -> ClassifyResult:
    by_id = {str(rule.id): rule for rule in rules}
    classified = unsorted = no_topic = adult = 0
    reasons: Counter[str] = Counter()
    for start in range(0, len(rows), BATCH_SIZE):  # bounds the decoded pixels held at once
        decoded: list[tuple[_Row, Image.Image]] = []
        for row in rows[start : start + BATCH_SIZE]:
            image = None
            try:
                image = open_working_copy(work, row.source_hash, row.ext)
            except WorkingCopyUnreadable:
                pass  # acted on below, outside the handler
            if image is None:
                mark_error(
                    conn, row.source_hash, WORKING_COPY_UNREADABLE, from_statuses=(_SANITIZED,)
                )
                reasons[WORKING_COPY_UNREADABLE] += 1
                log.warning("classify: %s error %s", row.short_hash, WORKING_COPY_UNREADABLE)
                continue
            decoded.append((row, image))
        if not decoded:
            continue
        images = [image for _, image in decoded]
        vectors = np.asarray(backend.embed_images(images), dtype=np.float32)
        nsfw = np.asarray(backend.nsfw_scores(images), dtype=np.float64)
        if vectors.shape != (len(images), IMAGE_VEC_DIM) or nsfw.shape != (len(images),):
            raise VisionError(_BAD_SHAPE)
        scores = max_over_prompts(
            score_matrix(
                cosine_matrix(vectors, text_vectors),
                mode=config.classify.score,
                logit_scale=backend.logit_scale,
                logit_bias=backend.logit_bias,
            ),
            prompts.category_ids,
        )
        for (row, _), vector, nsfw_score, per_category in zip(
            decoded, vectors, nsfw, scores, strict=True
        ):
            axes: dict[str, dict[str, float]] = {"format": {}, "topic": {}}
            for category_id, value in per_category.items():
                rule = by_id[category_id]
                axes[rule.axis][rule.name] = value
            branch = nsfw_branch(float(nsfw_score), config.nsfw.threshold)  # R-CLS-1
            choice = choose(axes["format"], axes["topic"], rules, branch, config.classify)
            moved = conn.execute(
                _CLASSIFIED,
                (
                    branch,
                    float(nsfw_score),
                    choice.format,
                    choice.topic,
                    Jsonb(choice.format_top),
                    Jsonb(choice.topic_top),
                    choice.needs_review,
                    choice.review_reason,
                    _vector_literal(vector),
                    row.source_hash,
                ),
            ).rowcount
            if moved != 1:  # no longer `sanitized`: another run got there first
                continue
            classified += 1
            unsorted += choice.format == "unsorted"
            no_topic += choice.topic is None
            adult += branch == "nsfw"
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
