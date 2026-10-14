"""CLS-002.2.3: the classify node against a real ledger, with a numeric vision double.

The double (`FakeVision`) is numbers only: an image's red channel picks which prompt it
matches, its green channel is its gate score. It stands in for the models so the node's own
work (selection, rules, writes, errors, idempotence) is tested on benign flat-colour images.
Names are artificial coinages. The replayed-model run is the integration acceptance test.
"""

import logging
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import psycopg
import pytest
import yaml
from PIL import Image

from classifier.config import Config
from classifier.graph.classify import (
    LEDGER_WRITE_FAILED,
    WORKING_COPY_UNREADABLE,
    ClassifyConfigError,
    ClassifyResult,
    classify,
)
from classifier.graph.nodes import NodeContext
from classifier.graph.sanitize import WorkDirError
from classifier.models.classify_rules import ClassifyRulesError
from classifier.models.siglip import BATCH_SIZE
from classifier.models.vision import VisionError

REPO = Path(__file__).resolve().parents[3]
DIM = 1152
SECRET = "Qorvex-Zhyndel-secret"  # planted in the source path and the sanitized name


def _hash(n: int) -> str:
    return f"{n:064x}"


class FakeVision:
    """Cosine 1 where an image's red value equals a prompt's index, else 0."""

    classifier_id = "fake-classifier"
    nsfw_id = "fake-gate"
    logit_scale = 1.0
    logit_bias = 0.0

    def __init__(self, fail_texts: bool = False) -> None:
        self.fail_texts = fail_texts
        self.text_calls = 0
        self.image_calls = 0
        self.seen: list[Image.Image] = []

    def _unit(self, index: int) -> np.ndarray:
        row = np.zeros(DIM, dtype=np.float32)
        row[index] = 1.0
        return row

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        self.text_calls += 1
        if self.fail_texts:
            raise VisionError("could not load the SigLIP weights; run `make models`")
        return np.stack([self._unit(i) for i in range(len(texts))])

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        self.image_calls += 1
        self.seen.extend(images)
        return np.stack([self._unit(image.getpixel((0, 0))[0]) for image in images])

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        return np.array([image.getpixel((0, 0))[1] / 255 for image in images], dtype=np.float32)


@pytest.fixture
def config() -> Config:
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    data["classify"]["score"] = "cosine"
    for axis in ("format", "topic"):
        data["classify"][axis]["default_min_score"] = 0.5
    return Config.model_validate(data)


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, results = tmp_path / "source", tmp_path / "results"
    (results / ".work").mkdir(parents=True)
    source.mkdir()
    return source, results


@pytest.fixture
def categories(db: psycopg.Connection) -> None:
    """Four synthetic categories, one prompt each, in prompt order 0..3."""
    db.execute("delete from categories")  # the seed; cascades to category_prompts
    for index, (axis, name) in enumerate(
        [("format", "Qorvex"), ("format", "Zhyndel"), ("topic", "Vrelk"), ("topic", "Qorvex")]
    ):
        category_id = db.execute(
            "insert into categories (axis, name, folder) values (%s, %s, %s) returning id",
            (axis, name, f"{name}-{axis}"),
        ).fetchone()[0]
        db.execute(
            "insert into category_prompts (category_id, position, prompt) values (%s, 0, %s)",
            (category_id, f"prompt number {index}"),
        )


def _add(db: psycopg.Connection, results: Path, n: int, red: int, green: int = 0) -> str:
    """A `sanitized` row with a flat-colour working copy; its source path holds a secret."""
    source_hash = _hash(n)
    Image.new("RGB", (4, 4), (red, green, 0)).save(results / ".work" / f"{source_hash}.png")
    db.execute(
        "insert into files (source_hash, short_hash, source_path, source_mtime, ext, status,"
        " original_sanitized) values (%s, %s, %s, now(), 'png', 'sanitized', %s)",
        (source_hash, source_hash[:8], f"/source/{SECRET}.png", f"{SECRET}-stem"),
    )
    return source_hash


def _ctx(folders: tuple[Path, Path], config: Config, vision: FakeVision) -> NodeContext:
    return NodeContext(folders[0], True, folders[1], config, vision=vision)


def _row(db: psycopg.Connection, source_hash: str) -> dict[str, object]:
    cursor = db.execute(
        "select status, branch, nsfw_score, format, topic, format_scores, topic_scores,"
        " needs_review, review_reason, image_vec is not null as has_vec, error"
        " from files where source_hash = %s",
        (source_hash,),
    )
    names = [c.name for c in cursor.description]
    return dict(zip(names, cursor.fetchone(), strict=True))


@pytest.mark.usefixtures("categories")
def test_a_format_and_no_topic_are_written(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 1, red=0)  # matches the format "Qorvex" only
    result = classify(db, _ctx(folders, config, FakeVision()))
    assert result == ClassifyResult(classified=1, no_topic=1)
    row = _row(db, h)
    assert (row["status"], row["branch"], row["format"], row["topic"]) == (
        "classified",
        "safe",
        "Qorvex",
        None,  # R-CLS-3b: the topic twin "Qorvex" is dropped, "Vrelk" scores 0
    )
    assert row["needs_review"] is False and row["review_reason"] is None
    assert row["format_scores"][0] == {"category": "Qorvex", "score": 1.0}
    assert len(row["format_scores"]) == 2 and len(row["topic_scores"]) == 2
    assert row["has_vec"] is True  # CLS-002.D10


@pytest.mark.usefixtures("categories")
def test_no_format_is_unsorted_for_review_but_the_topic_is_kept(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 2, red=2)  # matches the topic "Vrelk" only
    result = classify(db, _ctx(folders, config, FakeVision()))
    assert result == ClassifyResult(classified=1, unsorted=1)
    row = _row(db, h)
    assert (row["format"], row["topic"]) == ("unsorted", "Vrelk")
    assert (row["needs_review"], row["review_reason"]) == (True, "unsorted")


@pytest.mark.usefixtures("categories")
def test_the_gate_score_sets_the_branch_at_the_threshold(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    # A numeric double: green 255 scores 1.0, green 0 scores 0.0 (nsfw.threshold is 0.70).
    adult = _add(db, folders[1], 3, red=0, green=255)
    safe = _add(db, folders[1], 4, red=0, green=0)
    result = classify(db, _ctx(folders, config, FakeVision()))
    assert result.adult == 1 and result.classified == 2
    assert _row(db, adult)["branch"] == "nsfw" and _row(db, adult)["nsfw_score"] == 1.0
    assert _row(db, safe)["branch"] == "safe"


@pytest.mark.usefixtures("categories")
def test_a_safe_only_winner_falls_back_for_an_adult_image(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D2
    db.execute("update categories set branch = 'safe' where axis = 'format' and name = 'Qorvex'")
    h = _add(db, folders[1], 5, red=0, green=255)
    classify(db, _ctx(folders, config, FakeVision()))
    row = _row(db, h)
    assert (row["branch"], row["format"], row["needs_review"]) == ("nsfw", "unsorted", True)


@pytest.mark.usefixtures("categories")
def test_an_unreadable_working_copy_errors_only_that_file(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    caplog: pytest.LogCaptureFixture,
) -> None:  # CLS-002.D7
    bad, good = _add(db, folders[1], 6, red=0), _add(db, folders[1], 7, red=0)
    (folders[1] / ".work" / f"{bad}.png").write_bytes(b"not an image")
    db.execute(
        "insert into sanitize_log (source_hash, rule_id, field, before_hash, after_value)"
        " values (%s, 'r1', 'filename', %s, 'x')",
        (bad, "e" * 64),
    )
    with caplog.at_level(logging.INFO):
        result = classify(db, _ctx(folders, config, FakeVision()))
    assert (result.classified, result.errored) == (1, 1)
    assert dict(result.by_reason) == {WORKING_COPY_UNREADABLE: 1}
    assert _row(db, bad)["status"] == "error" and _row(db, bad)["error"] == WORKING_COPY_UNREADABLE
    assert _row(db, good)["status"] == "classified"
    log_rows = db.execute("select count(*) from sanitize_log where source_hash = %s", (bad,))
    assert log_rows.fetchone()[0] == 0
    text = caplog.text
    assert bad[:8] in text and SECRET not in text and str(folders[1]) not in text


@pytest.mark.usefixtures("categories")
def test_a_symlinked_working_copy_is_an_error_not_a_read(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 8, red=0)
    copy = folders[1] / ".work" / f"{h}.png"
    elsewhere = folders[1] / "elsewhere.png"
    copy.rename(elsewhere)
    copy.symlink_to(elsewhere)
    result = classify(db, _ctx(folders, config, FakeVision()))
    assert result.errored == 1 and _row(db, h)["status"] == "error"


@pytest.mark.usefixtures("categories")
def test_a_rerun_is_a_no_op(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    _add(db, folders[1], 9, red=0)
    classify(db, _ctx(folders, config, FakeVision()))
    again = FakeVision()
    assert classify(db, _ctx(folders, config, again)) == ClassifyResult()
    assert (again.text_calls, again.image_calls) == (0, 0)  # nothing selected, no model call


@pytest.mark.usefixtures("categories")
def test_prompts_are_encoded_once_and_images_in_batches(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D11
    for n in range(BATCH_SIZE + 1):
        _add(db, folders[1], 100 + n, red=0)
    vision = FakeVision()
    assert classify(db, _ctx(folders, config, vision)).classified == BATCH_SIZE + 1
    assert vision.text_calls == 1
    assert vision.image_calls == 2


@pytest.mark.usefixtures("categories")
def test_models_get_decoded_pixels_never_the_source_path(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    _add(db, folders[1], 10, red=0)  # the row's source_path does not exist on disk
    vision = FakeVision()
    classify(db, _ctx(folders, config, vision))
    assert len(vision.seen) == 1 and vision.seen[0].mode == "RGB"
    assert getattr(vision.seen[0], "filename", "") == ""


def _unchanged(db: psycopg.Connection, source_hash: str) -> None:
    assert _row(db, source_hash)["status"] == "sanitized"
    assert _row(db, source_hash)["format"] is None


@pytest.mark.usefixtures("categories")
def test_a_null_default_refuses_before_any_row_changes(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D4
    h = _add(db, folders[1], 11, red=0)
    db.execute("update categories set min_score = null")
    broken = config.model_copy(deep=True)
    broken.classify.format.default_min_score = None
    vision = FakeVision()
    with pytest.raises(ClassifyRulesError, match=r"classify\.format\.default_min_score"):
        classify(db, _ctx(folders, broken, vision))
    _unchanged(db, h)
    assert vision.text_calls == 0


@pytest.mark.usefixtures("categories")
def test_separate_mode_fails_fast_naming_the_key(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D9
    h = _add(db, folders[1], 12, red=0)
    separate = config.model_copy(deep=True)
    separate.nsfw.mode = "separate"
    with pytest.raises(ClassifyConfigError, match=r"nsfw\.mode"):
        classify(db, _ctx(folders, separate, FakeVision()))
    _unchanged(db, h)


@pytest.mark.usefixtures("categories")
def test_a_model_that_cannot_load_stops_the_run_with_fixed_text(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D7
    h = _add(db, folders[1], 13, red=0)
    with pytest.raises(VisionError, match="make models"):
        classify(db, _ctx(folders, config, FakeVision(fail_texts=True)))
    _unchanged(db, h)


@pytest.mark.usefixtures("categories")
def test_a_linked_work_folder_refuses_before_any_row_changes(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config, tmp_path: Path
) -> None:  # CLS-002.D8
    h = _add(db, folders[1], 14, red=0)
    (folders[1] / ".work").rename(tmp_path / "moved")
    (folders[1] / ".work").symlink_to(tmp_path / "moved")
    with pytest.raises(WorkDirError):
        classify(db, _ctx(folders, config, FakeVision()))
    _unchanged(db, h)


def test_the_node_needs_runs_transaction(
    folders: tuple[Path, Path], config: Config, migrated_db: str
) -> None:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        with pytest.raises(ValueError, match="transaction"):
            classify(conn, _ctx(folders, config, FakeVision()))


@pytest.mark.usefixtures("categories")
def test_one_rejected_write_errors_only_that_row(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    caplog: pytest.LogCaptureFixture,
) -> None:  # CLS-002.2.5: one savepoint per file
    first, bad, last = (_add(db, folders[1], n, red=0) for n in (20, 21, 22))
    # The ledger refuses to hold this one row as `classified`; the other rows are unaffected.
    db.execute(
        f"alter table files add constraint t_refuse check "
        f"(source_hash <> '{bad}' or status <> 'classified')"
    )
    with caplog.at_level(logging.INFO):
        result = classify(db, _ctx(folders, config, FakeVision()))
    assert (result.classified, result.errored) == (2, 1)
    assert dict(result.by_reason) == {LEDGER_WRITE_FAILED: 1}
    assert _row(db, first)["status"] == _row(db, last)["status"] == "classified"
    assert (_row(db, bad)["status"], _row(db, bad)["error"]) == ("error", LEDGER_WRITE_FAILED)
    assert bad[:8] in caplog.text and "t_refuse" not in caplog.text
