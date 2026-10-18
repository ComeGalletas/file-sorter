"""CLS-004.4: the classify node against a real ledger, with a numeric vision double and a scripted
Ollama.

`FakeVision` stands in for SigLIP and Falconsai (numbers only: an image's red channel is its
embedding index, its green channel the Falconsai score). `FakeOllama` is an `httpx.MockTransport`
handler that answers the VLM's two calls per image from a script keyed by the image's red
channel, and keeps every request body so the tests can check what a model was sent. Images are
benign flat colours generated here; names, categories and hints are artificial coinages. The
replayed-recording run is the integration acceptance test.
"""

import base64
import io
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

import httpx
import numpy as np
import psycopg
import pytest
import yaml
from PIL import Image

from classifier.config import Config, NsfwLevel
from classifier.graph.classify import (
    LEDGER_WRITE_FAILED,
    VLM_UNANSWERED,
    WORKING_COPY_UNREADABLE,
    ClassifyConfigError,
    ClassifyResult,
    classify,
)
from classifier.graph.nodes import NodeContext
from classifier.graph.sanitize import WorkDirError
from classifier.models.classify_rules import VlmAnswer
from classifier.models.ollama import OllamaUnavailable
from classifier.models.siglip import BATCH_SIZE
from classifier.models.vision import VisionError
from classifier.models.vlm_classify import VlmImageError

REPO = Path(__file__).resolve().parents[3]
DIM = 1152
PATH_SECRET = "Qorvex-Zhyndel-pathsecret"  # planted in source_path: no model may ever get it
HINT = "Vrelkhint_Xandozname"  # the sanitized name: only the classify call may carry it


def _hash(n: int) -> str:
    return f"{n:064x}"


class FakeVision:
    """Embedding one-hot at an image's red value; Falconsai score from its green channel."""

    classifier_id = "fake-classifier"
    nsfw_id = "fake-gate"
    logit_scale = 1.0
    logit_bias = 0.0

    def __init__(self, fail_images: bool = False) -> None:
        self.fail_images = fail_images
        self.text_calls = 0
        self.image_calls = 0
        self.seen: list[Image.Image] = []

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        self.text_calls += 1  # CLS-004.D7: the node no longer scores prompts
        raise AssertionError("the VLM path never embeds category prompts")

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        self.image_calls += 1
        if self.fail_images:
            raise VisionError("could not load the SigLIP weights; run `make models`")
        self.seen.extend(images)
        rows = []
        for image in images:
            row = np.zeros(DIM, dtype=np.float32)
            row[image.getpixel((0, 0))[0]] = 1.0
            rows.append(row)
        return np.stack(rows)

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        return np.array([image.getpixel((0, 0))[1] / 255 for image in images], dtype=np.float32)


@dataclass(frozen=True)
class Script:
    """What the scripted VLM answers for one image."""

    format: str = "Qorvex"
    topic: str = "none"
    level: str = "safe"
    fail: str | None = None  # "http": every call gets a 500; "down": Ollama is unreachable


class FakeOllama:
    """A scripted Ollama: answers by the red channel of the first image in each request."""

    def __init__(self, scripts: dict[int, Script] | None = None) -> None:
        self.scripts = scripts or {}
        self.requests: list[dict] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        self.requests.append(body)
        first = Image.open(io.BytesIO(base64.b64decode(body["images"][0]))).convert("RGB")
        red = first.getpixel((0, 0))[0]
        key = min(self.scripts or {0: Script()}, key=lambda k: abs(k - red))
        script = self.scripts.get(key, Script())
        if script.fail == "down":
            raise httpx.ConnectError("synthetic outage", request=request)
        if script.fail == "http":
            return httpx.Response(500)
        if "nsfw_level" in body["format"]["properties"]:
            answer = {"observation": "synthetic cues", "nsfw_level": script.level}
        else:
            answer = {
                "observation": "synthetic cues",
                "format": script.format,
                "topic": script.topic,
            }
        return httpx.Response(200, json={"response": json.dumps(answer)})

    def calls(self, kind: str) -> list[dict]:
        """The requests of one call: `classify` (format and topic) or `nsfw` (the level)."""
        has_level = [("nsfw_level" in r["format"]["properties"]) for r in self.requests]
        return [
            r for r, lvl in zip(self.requests, has_level, strict=True) if lvl == (kind == "nsfw")
        ]


@pytest.fixture(autouse=True)
def ollama_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")


@pytest.fixture
def config() -> Config:
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    data["nsfw"]["min_level"] = "nudity"
    data["nsfw"]["cross_check"] = {"safe_above": None, "adult_below": None}
    return Config.model_validate(data)


@pytest.fixture
def folders(tmp_path: Path) -> tuple[Path, Path]:
    source, results = tmp_path / "source", tmp_path / "results"
    (results / ".work").mkdir(parents=True)
    source.mkdir()
    return source, results


@pytest.fixture
def categories(db: psycopg.Connection) -> None:
    """Four synthetic categories: two formats, and two topics one of which twins a format."""
    db.execute("delete from categories")  # the seed
    for axis, name in [
        ("format", "Qorvex"),
        ("format", "Zhyndel"),
        ("topic", "Vrelk"),
        ("topic", "Qorvex"),
    ]:
        db.execute(
            "insert into categories (axis, name, folder) values (%s, %s, %s)",
            (axis, name, f"{name}-{axis}"),
        )


def _add(
    db: psycopg.Connection,
    results: Path,
    n: int,
    red: int = 0,
    green: int = 0,
    hint: str | None = HINT,
) -> str:
    """A `sanitized` row with a flat-colour working copy; its source path holds a secret."""
    source_hash = _hash(n)
    Image.new("RGB", (4, 4), (red, green, 0)).save(results / ".work" / f"{source_hash}.png")
    db.execute(
        "insert into files (source_hash, short_hash, source_path, source_mtime, ext, status,"
        " original_sanitized) values (%s, %s, %s, now(), 'png', 'sanitized', %s)",
        (source_hash, source_hash[:8], f"/source/{PATH_SECRET}.png", hint),
    )
    return source_hash


def _ctx(
    folders: tuple[Path, Path], config: Config, vision: FakeVision, ollama: FakeOllama
) -> NodeContext:
    return NodeContext(
        folders[0], True, folders[1], config, ollama_transport=ollama.transport(), vision=vision
    )


def _row(db: psycopg.Connection, source_hash: str) -> dict[str, object]:
    cursor = db.execute(
        "select status, branch, nsfw_score, nsfw_level, format, topic, format_scores,"
        " topic_scores, needs_review, review_reason, image_vec is not null as has_vec, error"
        " from files where source_hash = %s",
        (source_hash,),
    )
    names = [c.name for c in cursor.description]
    return dict(zip(names, cursor.fetchone(), strict=True))


@pytest.mark.usefixtures("categories")
def test_format_topic_and_level_are_written(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 1, red=0, green=51)
    ollama = FakeOllama({0: Script("Zhyndel", "Vrelk", "safe")})
    result = classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert result == ClassifyResult(classified=1)
    row = _row(db, h)
    assert (row["status"], row["branch"], row["nsfw_level"]) == ("classified", "safe", "safe")
    assert (row["format"], row["topic"]) == ("Zhyndel", "Vrelk")
    assert row["needs_review"] is False and row["review_reason"] is None
    assert row["nsfw_score"] == pytest.approx(51 / 255)  # Falconsai's score stays as evidence
    assert row["format_scores"] is None and row["topic_scores"] is None  # CLS-004.D7
    assert row["has_vec"] is True  # CLS-002.D10: SigLIP still embeds


@pytest.mark.usefixtures("categories")
def test_a_topic_that_twins_the_format_is_dropped(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # R-CLS-3b, CLS-002.D3
    h = _add(db, folders[1], 2)
    ollama = FakeOllama({0: Script("Qorvex", "Qorvex", "safe")})
    result = classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert result == ClassifyResult(classified=1, no_topic=1)
    assert (_row(db, h)["format"], _row(db, h)["topic"]) == ("Qorvex", None)


@pytest.mark.usefixtures("categories")
def test_unsorted_is_for_review_but_the_topic_is_kept(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 3)
    ollama = FakeOllama({0: Script("unsorted", "Vrelk", "safe")})
    result = classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert result == ClassifyResult(classified=1, unsorted=1)
    row = _row(db, h)
    assert (row["format"], row["topic"]) == ("unsorted", "Vrelk")
    assert (row["needs_review"], row["review_reason"]) == (True, "unsorted")


@pytest.mark.usefixtures("categories")
@pytest.mark.parametrize(
    ("level", "branch"),
    [("safe", "safe"), ("suggestive", "safe"), ("nudity", "nsfw"), ("explicit", "nsfw")],
)
def test_the_branch_follows_the_level_against_min_level(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    level: str,
    branch: str,
) -> None:  # CLS-004.D3
    h = _add(db, folders[1], 4)
    ollama = FakeOllama({0: Script(level=level)})
    result = classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert (_row(db, h)["branch"], _row(db, h)["nsfw_level"]) == (branch, level)
    assert result.adult == (branch == "nsfw")


@pytest.mark.usefixtures("categories")
def test_a_changed_min_level_moves_the_branch_but_not_the_stored_level(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 5)
    config.nsfw.min_level = NsfwLevel.suggestive
    ollama = FakeOllama({0: Script(level="suggestive")})
    classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert (_row(db, h)["branch"], _row(db, h)["nsfw_level"]) == ("nsfw", "suggestive")


@pytest.mark.usefixtures("categories")
def test_a_safe_only_format_falls_back_for_an_adult_image(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D2
    db.execute("update categories set branch = 'safe' where axis = 'format' and name = 'Qorvex'")
    h = _add(db, folders[1], 6)
    ollama = FakeOllama({0: Script("Qorvex", "none", "explicit")})
    classify(db, _ctx(folders, config, FakeVision(), ollama))
    row = _row(db, h)
    assert (row["branch"], row["format"], row["needs_review"]) == ("nsfw", "unsorted", True)


@pytest.mark.usefixtures("categories")
def test_the_hint_reaches_only_the_classify_call_and_the_path_reaches_no_call(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-004.D2, D6, P-2
    _add(db, folders[1], 7)
    ollama = FakeOllama()
    classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert len(ollama.calls("classify")) == 1 and len(ollama.calls("nsfw")) == 1
    assert HINT in json.dumps(ollama.calls("classify")[0])
    assert HINT not in json.dumps(ollama.calls("nsfw")[0])
    assert PATH_SECRET not in json.dumps(ollama.requests)
    assert {r["model"] for r in ollama.requests} == {config.models.vlm_safe}


@pytest.mark.usefixtures("categories")
@pytest.mark.parametrize("hint", [None, "", "   "])
def test_a_missing_or_blank_name_gives_no_hint(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config, hint: str | None
) -> None:  # CLS-004.D6: fail closed
    h = _add(db, folders[1], 8, hint=hint)
    ollama = FakeOllama()
    classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert _row(db, h)["status"] == "classified"
    assert PATH_SECRET not in json.dumps(ollama.requests)


@pytest.mark.usefixtures("categories")
def test_an_animated_copy_gives_the_level_call_three_frames_and_classify_one(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-004.D2
    h = _hash(9)
    frames = [Image.new("RGB", (4, 4), (0, 0, c)) for c in (10, 120, 240, 60, 200)]
    frames[0].save(
        folders[1] / ".work" / f"{h}.gif", save_all=True, append_images=frames[1:], duration=50
    )
    db.execute(
        "insert into files (source_hash, short_hash, source_path, source_mtime, ext, status)"
        " values (%s, %s, %s, now(), 'gif', 'sanitized')",
        (h, h[:8], f"/source/{PATH_SECRET}.gif"),
    )
    ollama = FakeOllama()
    classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert len(ollama.calls("classify")[0]["images"]) == 1
    assert len(ollama.calls("nsfw")[0]["images"]) == 3
    assert _row(db, h)["status"] == "classified"


@pytest.mark.usefixtures("categories")
def test_an_unreadable_working_copy_errors_only_that_file(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    caplog: pytest.LogCaptureFixture,
) -> None:  # CLS-002.D7
    bad, good = _add(db, folders[1], 10), _add(db, folders[1], 11)
    (folders[1] / ".work" / f"{bad}.png").write_bytes(b"not an image")
    db.execute(
        "insert into sanitize_log (source_hash, rule_id, field, before_hash, after_value)"
        " values (%s, 'r1', 'filename', %s, 'x')",
        (bad, "e" * 64),
    )
    ollama = FakeOllama()
    with caplog.at_level(logging.INFO):
        result = classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert (result.classified, result.errored) == (1, 1)
    assert dict(result.by_reason) == {WORKING_COPY_UNREADABLE: 1}
    assert _row(db, bad)["status"] == "error" and _row(db, bad)["error"] == WORKING_COPY_UNREADABLE
    assert _row(db, good)["status"] == "classified"
    assert len(ollama.requests) == 2  # the bad file never reached the model
    log_rows = db.execute("select count(*) from sanitize_log where source_hash = %s", (bad,))
    assert log_rows.fetchone()[0] == 0
    text = caplog.text
    assert bad[:8] in text and PATH_SECRET not in text and HINT not in text
    assert str(folders[1]) not in text


@pytest.mark.usefixtures("categories")
def test_a_symlinked_working_copy_is_an_error_not_a_read(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    h = _add(db, folders[1], 12)
    copy = folders[1] / ".work" / f"{h}.png"
    elsewhere = folders[1] / "elsewhere.png"
    copy.rename(elsewhere)
    copy.symlink_to(elsewhere)
    result = classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    assert result.errored == 1 and _row(db, h)["status"] == "error"


@pytest.mark.usefixtures("categories")
def test_a_rerun_is_a_no_op(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    _add(db, folders[1], 13)
    classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    again, ollama = FakeVision(), FakeOllama()
    assert classify(db, _ctx(folders, config, again, ollama)) == ClassifyResult()
    assert (again.image_calls, len(ollama.requests)) == (0, 0)  # nothing selected, no model call


@pytest.mark.usefixtures("categories")
def test_images_go_to_siglip_in_batches_and_the_vlm_gets_two_calls_each(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    for n in range(BATCH_SIZE + 1):
        _add(db, folders[1], 100 + n)
    vision, ollama = FakeVision(), FakeOllama()
    assert classify(db, _ctx(folders, config, vision, ollama)).classified == BATCH_SIZE + 1
    assert (vision.image_calls, vision.text_calls) == (2, 0)
    assert len(ollama.requests) == 2 * (BATCH_SIZE + 1)


@pytest.mark.usefixtures("categories")
def test_siglip_gets_decoded_first_frame_pixels_never_the_source_path(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:
    _add(db, folders[1], 14)  # the row's source_path does not exist on disk
    vision = FakeVision()
    classify(db, _ctx(folders, config, vision, FakeOllama()))
    assert len(vision.seen) == 1 and vision.seen[0].mode == "RGB"
    assert getattr(vision.seen[0], "filename", "") == ""


def _unchanged(db: psycopg.Connection, source_hash: str) -> None:
    assert _row(db, source_hash)["status"] == "sanitized"
    assert _row(db, source_hash)["format"] is None


@pytest.mark.usefixtures("categories")
def test_a_null_score_default_no_longer_refuses(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-004.D7: nothing compares a score on the VLM path
    h = _add(db, folders[1], 15)
    db.execute("update categories set min_score = null")
    classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    assert _row(db, h)["status"] == "classified"


@pytest.mark.usefixtures("categories")
def test_separate_mode_fails_fast_naming_the_key(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D9
    h = _add(db, folders[1], 16)
    separate = config.model_copy(deep=True)
    separate.nsfw.mode = "separate"
    with pytest.raises(ClassifyConfigError, match=r"nsfw\.mode"):
        classify(db, _ctx(folders, separate, FakeVision(), FakeOllama()))
    _unchanged(db, h)


@pytest.mark.usefixtures("categories")
def test_a_model_that_cannot_load_stops_the_run_with_fixed_text(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # CLS-002.D7
    h = _add(db, folders[1], 17)
    ollama = FakeOllama()
    with pytest.raises(VisionError, match="make models"):
        classify(db, _ctx(folders, config, FakeVision(fail_images=True), ollama))
    _unchanged(db, h)
    assert ollama.requests == []


@pytest.mark.usefixtures("categories")
def test_a_linked_work_folder_refuses_before_any_row_changes(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config, tmp_path: Path
) -> None:  # CLS-002.D8
    h = _add(db, folders[1], 18)
    (folders[1] / ".work").rename(tmp_path / "moved")
    (folders[1] / ".work").symlink_to(tmp_path / "moved")
    with pytest.raises(WorkDirError):
        classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    _unchanged(db, h)


def test_the_node_needs_runs_transaction(
    folders: tuple[Path, Path], config: Config, migrated_db: str
) -> None:
    with psycopg.connect(migrated_db, autocommit=True) as conn:
        with pytest.raises(ValueError, match="transaction"):
            classify(conn, _ctx(folders, config, FakeVision(), FakeOllama()))


@pytest.mark.usefixtures("categories")
def test_one_rejected_write_errors_only_that_row(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    caplog: pytest.LogCaptureFixture,
) -> None:  # CLS-002.2.5: one savepoint per file
    first, bad, last = (_add(db, folders[1], n) for n in (20, 21, 22))
    # The ledger refuses to hold this one row as `classified`; the other rows are unaffected.
    db.execute(
        f"alter table files add constraint t_refuse check "
        f"(source_hash <> '{bad}' or status <> 'classified')"
    )
    with caplog.at_level(logging.INFO):
        result = classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    assert (result.classified, result.errored) == (2, 1)
    assert dict(result.by_reason) == {LEDGER_WRITE_FAILED: 1}
    assert _row(db, first)["status"] == _row(db, last)["status"] == "classified"
    assert (_row(db, bad)["status"], _row(db, bad)["error"]) == ("error", LEDGER_WRITE_FAILED)
    assert bad[:8] in caplog.text and "t_refuse" not in caplog.text


# --- a failed answer, the Falconsai cross-check (CLS-004.4.3, CLS-004.D4, D5) ----------------


@pytest.mark.usefixtures("categories")
def test_an_unanswered_file_errors_after_one_retry_and_the_batch_goes_on(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    caplog: pytest.LogCaptureFixture,
) -> None:
    mute, fine = _add(db, folders[1], 30, red=0), _add(db, folders[1], 31, red=200)
    db.execute(
        "insert into sanitize_log (source_hash, rule_id, field, before_hash, after_value)"
        " values (%s, 'r1', 'filename', %s, 'x')",
        (mute, "e" * 64),
    )
    ollama = FakeOllama({0: Script(fail="http"), 200: Script("Zhyndel")})
    with caplog.at_level(logging.INFO):
        result = classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert (result.classified, result.errored) == (1, 1)
    assert dict(result.by_reason) == {VLM_UNANSWERED: 1}
    row = _row(db, mute)
    assert (row["status"], row["error"], row["format"]) == ("error", VLM_UNANSWERED, None)
    assert _row(db, fine)["status"] == "classified"
    assert len(ollama.calls("classify")) == 3 and len(ollama.calls("nsfw")) == 1  # 2 tries + 1
    assert db.execute("select count(*) from sanitize_log").fetchone()[0] == 0
    assert db.execute(
        "select original_sanitized from files where source_hash = %s", (mute,)
    ).fetchone() == (None,)
    assert mute[:8] in caplog.text and VLM_UNANSWERED in caplog.text
    assert HINT not in caplog.text and PATH_SECRET not in caplog.text


@pytest.mark.usefixtures("categories")
def test_a_name_the_rules_do_not_know_counts_as_unanswered(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _add(db, folders[1], 32)

    def stray(*_args: object, **_kwargs: object) -> VlmAnswer:
        return VlmAnswer(format="Nonexistent", topic=None, level=NsfwLevel.safe)

    monkeypatch.setattr("classifier.graph.classify.vlm_classify", stray)
    result = classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    assert dict(result.by_reason) == {VLM_UNANSWERED: 1}
    assert (_row(db, h)["status"], _row(db, h)["error"]) == ("error", VLM_UNANSWERED)


@pytest.mark.usefixtures("categories")
def test_an_undecodable_frame_is_an_unreadable_copy(
    db: psycopg.Connection,
    folders: tuple[Path, Path],
    config: Config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    h = _add(db, folders[1], 33)

    def broken(*_args: object, **_kwargs: object) -> VlmAnswer:
        raise VlmImageError("fixed text")

    monkeypatch.setattr("classifier.graph.classify.vlm_classify", broken)
    result = classify(db, _ctx(folders, config, FakeVision(), FakeOllama()))
    assert dict(result.by_reason) == {WORKING_COPY_UNREADABLE: 1}
    assert _row(db, h)["error"] == WORKING_COPY_UNREADABLE


@pytest.mark.usefixtures("categories")
def test_ollama_being_unreachable_stops_the_node_instead_of_erroring_files(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # run rolls the node back: nothing says this file is at fault
    h = _add(db, folders[1], 34)
    ollama = FakeOllama({0: Script(fail="down")})
    with pytest.raises(OllamaUnavailable) as caught:
        classify(db, _ctx(folders, config, FakeVision(), ollama))
    assert HINT not in str(caught.value) and PATH_SECRET not in str(caught.value)
    assert _row(db, h)["status"] == "sanitized"  # never marked `error`


@pytest.fixture
def cross_checked(config: Config) -> Config:
    config.nsfw.cross_check.safe_above = 0.9
    config.nsfw.cross_check.adult_below = 0.1
    return config


@pytest.mark.usefixtures("categories")
def test_a_strong_disagreement_sets_review_and_never_the_branch(
    db: psycopg.Connection, folders: tuple[Path, Path], cross_checked: Config
) -> None:
    says_safe = _add(db, folders[1], 40, red=0, green=255)  # VLM safe, Falconsai 1.0
    says_adult = _add(db, folders[1], 41, red=100, green=0)  # VLM explicit, Falconsai 0.0
    agrees = _add(db, folders[1], 42, red=200, green=0)  # VLM safe, Falconsai 0.0
    ollama = FakeOllama(
        {0: Script(level="safe"), 100: Script(level="explicit"), 200: Script(level="safe")}
    )
    classify(db, _ctx(folders, cross_checked, FakeVision(), ollama))
    one, two, three = (_row(db, h) for h in (says_safe, says_adult, agrees))
    assert (one["branch"], one["needs_review"], one["review_reason"]) == (
        "safe",
        True,
        "nsfw_disagreement",
    )
    assert (two["branch"], two["needs_review"], two["review_reason"]) == (
        "nsfw",
        True,
        "nsfw_disagreement",
    )
    assert (three["branch"], three["needs_review"]) == ("safe", False)


@pytest.mark.usefixtures("categories")
def test_no_thresholds_means_no_cross_check(
    db: psycopg.Connection, folders: tuple[Path, Path], config: Config
) -> None:  # both null: the cross-check is off
    h = _add(db, folders[1], 43, red=0, green=255)
    classify(db, _ctx(folders, config, FakeVision(), FakeOllama({0: Script(level="safe")})))
    assert _row(db, h)["needs_review"] is False
