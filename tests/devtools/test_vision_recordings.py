"""TST-008.1: the vision recording format, replay, recorder and lint (TST-008.D3).

Unit tier: every image is synthetic and generated here, every recording lives under `tmp_path`,
and no model is loaded. The planted SECRET stands in for a name or path that must never appear in
an error. NSFW recordings hold a score for a plain colour block, nothing more.
"""

import base64
import hashlib
import io
import json
import struct
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from classifier.models.vision import VisionBackend
from tests.recordings import vision
from tests.recordings.replay import RecordingError, lint_recordings, recording_key
from tests.recordings.vision import (
    TEXT_RULE,
    _test_models,
    check_request,
    check_text_input,
    config_models,
    decode_array,
    encode_array,
    image_digest,
    load_vision_recording,
    register_test_model,
    unregister_test_model,
    vision_key,
)
from tests.recordings.vision_backend import (
    TOLERANCE,
    RecordingVisionBackend,
    ReplayVisionBackend,
)

MODEL = "synthetic/vision-model"
CLASSIFIER = "synthetic/classifier"
NSFW = "synthetic/nsfw"
OTHER_MODEL = "synthetic/other"


@pytest.fixture(autouse=True)
def synthetic_models(extra_vision_models: Any) -> None:
    """The lint accepts only config.yaml's vision models (TST-008.D9); register ours per test."""
    extra_vision_models(MODEL, CLASSIFIER, NSFW, OTHER_MODEL)


SECRET = "zzplantedsecretqx"
DIGEST = "a" * 64

# A copy of every default prompt in DESIGN.md §4.3 (both tables). CLS-002.2 records replays with
# these, so the prompt text rule must accept all of them.
DESIGN_PROMPTS = [
    "a photo taken with a camera",
    "a portrait",
    "a photo of an object",
    "a screenshot taken inside a video game",
    "a video game scene with a game HUD",
    "a video game character in a 3D game world",
    "a screenshot of a phone",
    "a screenshot of a desktop app or website",
    "a cropped screen capture of part of a window",
    "a snippet of a webpage, chat or app",
    "a meme with text",
    "a reaction image",
    "a digital illustration",
    "a drawing",
    "concept art",
    "an animated abstract graphic",
    "a scanned document",
    "a receipt",
    "a form",
    "a video game screenshot",
    "a video game character",
    "a game user interface",
    "an anime character",
    "manga style art",
    "a western cartoon character",
    "a comic drawing",
    "a computer case",
    "PC hardware components",
    "a photo of a cat",
    "a photo of a dog",
    "an animal",
    "a photo of people",
    "a person's face",
    "a landscape",
    "a beach",
    "a cityscape",
    "a view from a high floor",
    "a list of song names",
    "a music player",
    "a still from a TV show",
    "a code editor",
    "a mobile app screen",
    "a joke or humorous image",
    "an image with an ironic meaning",
    "a document",
    "a list of text",
]


def block(
    color: tuple[int, int, int] = (200, 30, 30), size: tuple[int, int] = (8, 6)
) -> Image.Image:
    return Image.new("RGB", size, color)


def named_block() -> Image.Image:
    """A block that claims to come from a file named SECRET: the key and errors must ignore it."""
    image = block()
    image.filename = f"/host/{SECRET}.png"  # type: ignore[attr-defined]
    return image


def assert_private(exc: BaseException) -> None:
    assert SECRET not in str(exc) and SECRET not in repr(exc)
    assert exc.__cause__ is None
    assert exc.__suppress_context__ or exc.__context__ is None


def write_vision(root: Path, model: str, kind: str, value: str, array: Any) -> Path:
    path = root / "pkg" / f"{vision_key(model, kind, value)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    request = {"model": model, "kind": kind, "input": value}
    path.write_text(
        json.dumps({"request": request, "response": encode_array(array)}), encoding="utf-8"
    )
    return path


# --- the key (TST-008.D3) ---


def test_key_is_the_sha256_of_the_canonical_json() -> None:
    text = '{"input":"p","kind":"image","model":"m"}'
    assert vision_key("m", "image", "p") == hashlib.sha256(text.encode()).hexdigest()


def test_key_is_pinned() -> None:
    # Hand-computed once; a change here means every committed recording must be re-keyed.
    assert (
        vision_key("m", "image", "p")
        == "c1e966916888c133a48f6dcc3528a4ebf8d2768f280d15cf7237cccd02e61b3a"
    )


@pytest.mark.parametrize("field", ["model", "kind", "input"])
def test_every_field_changes_the_key(field: str) -> None:
    base = {"model": "m", "kind": "image", "input": "p"}
    other = {**base, field: "nsfw" if field == "kind" else "other"}
    assert vision_key(**base) != vision_key(**other)


def test_non_ascii_is_hashed_as_utf8_not_escaped() -> None:
    text = json.dumps(
        {"model": "m", "kind": "image", "input": "café – 東京"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert vision_key("m", "image", "café – 東京") == hashlib.sha256(text.encode()).hexdigest()


def test_lone_surrogate_and_unknown_kind_fail_without_echoing() -> None:
    with pytest.raises(RecordingError) as caught:
        vision_key("m", "image", f"{SECRET}\ud800")
    assert_private(caught.value)
    with pytest.raises(RecordingError) as caught:
        vision_key("m", SECRET, "p")
    assert_private(caught.value)


# --- the image digest ---


def test_image_digest_follows_mode_size_and_pixels() -> None:
    base = image_digest(block())
    assert base == image_digest(block())
    assert len({base, image_digest(block((201, 30, 30))), image_digest(block(size=(6, 8)))}) == 3
    assert image_digest(block().convert("L")) != base
    assert image_digest(block().convert("RGBA")) != base


def test_image_digest_ignores_the_file_it_came_from(tmp_path: Path) -> None:
    first, second = tmp_path / f"{SECRET}-a.png", tmp_path / "b.png"
    block().save(first)
    block().save(second)
    with Image.open(first) as a, Image.open(second) as b:
        assert image_digest(a) == image_digest(b) == image_digest(block())


def test_image_digest_uses_the_first_frame_only() -> None:
    first = Image.new("RGB", (4, 4), (250, 10, 10))
    second = Image.new("RGB", (4, 4), (10, 10, 250))
    buffer = io.BytesIO()
    first.save(buffer, format="GIF", save_all=True, append_images=[second], duration=50)
    buffer.seek(0)
    with Image.open(buffer) as gif:
        assert gif.n_frames == 2
        gif.seek(0)
        at_first = image_digest(gif)
        gif.seek(1)
        second_frame = gif.tobytes()
        assert image_digest(gif) == at_first  # it seeks back to frame 0 itself
        assert second_frame != gif.tobytes()  # and the object now sits on frame 0


def test_image_digest_is_length_prefixed() -> None:
    # 2x3 and 3x2 of the same bytes, and a mode change, must not collide.
    flat = Image.frombytes("L", (2, 3), bytes(range(6)))
    tall = Image.frombytes("L", (3, 2), bytes(range(6)))
    assert image_digest(flat) != image_digest(tall)


def test_image_digest_failure_is_fixed_text() -> None:
    class Broken:
        mode = "RGB"
        size = (1, 1)

        def seek(self, frame: int) -> None:
            raise OSError(f"cannot read /host/{SECRET}.png")

        def tobytes(self) -> bytes:  # pragma: no cover
            return b""

    with pytest.raises(RecordingError) as caught:
        image_digest(Broken())  # type: ignore[arg-type]
    assert_private(caught.value)


# --- the array codec ---


def test_array_round_trip_is_bit_exact() -> None:
    values = np.array([0.0, -0.0, 1.5, -3.25, 1e-45, 3.4e38], dtype=np.float32)
    back = decode_array(encode_array(values))
    assert back.dtype == np.float32 and back.shape == values.shape
    assert back.tobytes() == values.tobytes()  # -0.0 and the subnormal survive
    assert not back.flags.writeable


def test_encoding_is_little_endian_float32_with_the_shape() -> None:
    encoded = encode_array(np.array([[1.0, 2.0]], dtype=np.float64))
    assert encoded == {
        "shape": [1, 2],
        "dtype": "float32",
        "data": base64.b64encode(struct.pack("<ff", 1.0, 2.0)).decode(),
    }
    assert encode_array(np.float32(0.5))["shape"] == []
    assert decode_array(encode_array(np.float32(0.5))).shape == ()


def test_a_big_endian_payload_is_not_read_as_little_endian() -> None:
    big = base64.b64encode(struct.pack(">f", 1.0)).decode()
    got = decode_array({"shape": [1], "dtype": "float32", "data": big})
    assert got[0] != 1.0


def test_nan_and_inf_are_refused() -> None:
    with pytest.raises(RecordingError):
        encode_array(np.array([np.nan], dtype=np.float32))
    nan = base64.b64encode(struct.pack("<f", float("inf"))).decode()
    with pytest.raises(RecordingError):
        decode_array({"shape": [1], "dtype": "float32", "data": nan})


@pytest.mark.parametrize(
    "response",
    [
        None,
        [],
        {"shape": [1], "dtype": "float32"},
        {"shape": [1], "dtype": "float32", "data": "AAAAAA==", "extra": 1},
        {"shape": [1], "dtype": "float64", "data": "AAAAAA=="},
        {"shape": [2], "dtype": "float32", "data": "AAAAAA=="},  # length mismatch
        {"shape": [1], "dtype": "float32", "data": "AAAAAA"},  # not strict base64
        {"shape": [1], "dtype": "float32", "data": "!!!!"},
        {"shape": [1], "dtype": "float32", "data": 5},
        {"shape": "1", "dtype": "float32", "data": "AAAAAA=="},
        {"shape": [-1], "dtype": "float32", "data": ""},
        {"shape": [True], "dtype": "float32", "data": "AAAAAA=="},
        {"shape": [1, 1, 1], "dtype": "float32", "data": "AAAAAA=="},  # rank
        {"shape": [4097], "dtype": "float32", "data": base64.b64encode(bytes(4 * 4097)).decode()},
        {"shape": [1], "dtype": "float32", "data": "é"},
    ],
)
def test_a_malformed_response_is_refused_with_fixed_text(response: object) -> None:
    with pytest.raises(RecordingError) as caught:
        decode_array(response)
    assert_private(caught.value)


# --- the prompt text rule (prompts.py slots and image request prompts, TST-008.D9) ---


@pytest.mark.parametrize("prompt", DESIGN_PROMPTS)
def test_every_design_seed_prompt_is_accepted(prompt: str) -> None:
    check_text_input(prompt)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "two\nlines",
        "x" * 257,
        "/leading/slash",
        "C:/Users/someone",
        "C:\\dir",
        "back\\slash",
        "../up",
        "folder/qorvex.png",
        "qorvex.JPG",
        "notes.txt",
        "tab\there",
        # The privacy auditor's probes (PR #113): names, stems and paths the first rule missed.
        "sample.CR2",
        "clip.mkv",
        "report.docx",
        "archive.zip",
        "sample.NEF",
        "sample.dng",
        "Pictures/family",
        "IMG_0042",
        "~/Pictures/trip",
        "DSC-1234",
        "IMG0042",
        "a photo and/or a drawing",
        "a: b",
        "café",
        "under_score",
        # Round 3: names and paths the rule refuses (TST-008.1.7).
        "photo_2023.jpeg",
        "/home/u/x",
        "Desktop\\pic",
        # Round 2 probes (PR #113): extensions after a bracket, quote or space, split stems.
        "holiday (1).jpg",
        "beach .jpg",
        "sunset'.jpg",
        "trip-photo .jpg",
        "IMG 0042",
        "P1010234",
        # TST-008.D9: the set is letters, digits, single spaces, comma and apostrophe only.
        "a cat.",
        "a (cat)",
        "a-cat",
        "a  cat",
        " a cat",
        "a cat ",
        "'",
        ",",
        "12 34",
        "taken 2019 05 07",
        "a cat ",
    ],
)
def test_text_outside_the_allowlist_is_refused(text: str) -> None:
    with pytest.raises(RecordingError) as caught:
        check_text_input(text)
    assert_private(caught.value)


@pytest.mark.parametrize(
    "text",
    ["a person's face", "a snippet of a webpage, chat or app", "PC gear", "3D art", "12 cats, 99"],
)
def test_the_allowed_characters_and_two_digits_per_word_pass(text: str) -> None:
    check_text_input(text)


def test_the_text_error_says_exactly_what_the_rule_allows() -> None:
    with pytest.raises(RecordingError) as caught:
        check_text_input("IMG_0042")
    assert str(caught.value) == TEXT_RULE


def test_the_config_models_are_the_committed_vision_ids() -> None:
    assert config_models() == {"google/siglip-so400m-patch14-384", "Falconsai/nsfw_image_detection"}


@pytest.mark.parametrize(
    "model", ["google/siglip-so400m-patch14-384", "Falconsai/nsfw_image_detection", MODEL]
)
def test_a_config_model_or_a_registered_test_id_is_accepted(model: str) -> None:
    request = {"model": model, "kind": "nsfw", "input": DIGEST}
    assert check_request(request) == request


def test_a_registered_test_id_is_gone_after_unregistering() -> None:
    assert "synthetic/unregistered" not in _test_models
    register_test_model("synthetic/unregistered")
    unregister_test_model("synthetic/unregistered")
    with pytest.raises(RecordingError):
        check_request({"model": "synthetic/unregistered", "kind": "nsfw", "input": DIGEST})


@pytest.mark.parametrize(
    "model",
    [
        "a",
        "/models/x",
        "a/b/c",
        "a/../b",
        "a b/c",
        "x:y/z",
        "",
        "Pictures/family",
        "Desktop/pic",
        "fixtures" + "/" + "images",  # split: the tier audit flags the literal path text
        "google/other",
        "synthetic/",
        "synthetic/Upper",
        "synthetic/under_score",
        "synthetic/x" + "y" * 40,
        "synthetic/a/b",
        "Synthetic/x",
    ],
)
def test_a_test_registration_must_be_a_synthetic_name(model: str) -> None:
    with pytest.raises(RecordingError):
        register_test_model(model)
    assert model not in _test_models


def test_an_unreadable_config_fails_with_fixed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vision, "CONFIG_FILE", Path("/nonexistent") / SECRET / "config.yaml")
    with pytest.raises(RecordingError) as caught:
        config_models()
    assert str(caught.value) == "config.yaml could not be read for the vision model ids"
    assert_private(caught.value)


@pytest.mark.parametrize(
    "model",
    [
        "",
        "model",
        "/models/x",
        "C:\\x",
        "../x",
        "~/x",
        "a/../b",
        "a/b/c",
        "a b/c",
        "x" * 97 + "/y",
        f"{SECRET}/x:y",
        # Round 2 probes: folder paths that have the owner/name shape.
        "Pictures/family",
        "Desktop/pic",
        "fixtures" + "/" + "images",  # split: the tier audit flags the literal path text
        # Well-formed, but not in config.yaml.
        "synthetic/unregistered",
        "google/siglip-so400m-patch14-384/",
        "google/SIGLIP-so400m-patch14-384",
    ],
)
def test_a_path_shaped_model_id_is_refused_by_the_request_and_the_recorder(
    model: str, tmp_path: Path
) -> None:
    with pytest.raises(RecordingError) as caught:
        check_request({"model": model, "kind": "nsfw", "input": DIGEST})
    assert_private(caught.value)

    class Local(FakeUpstream):
        classifier_id = model

    recorder = RecordingVisionBackend("pkg", Local(), TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError) as caught:
        recorder.embed_images([block()])
    assert_private(caught.value)
    assert not (tmp_path / "pkg").exists()


@pytest.mark.parametrize("kind", ["image", "nsfw"])
def test_an_image_or_nsfw_input_must_be_a_hash(kind: str) -> None:
    for bad in (SECRET, "ABC" * 22, "a" * 63, "/a/b.png"):
        with pytest.raises(RecordingError) as caught:
            check_request({"model": MODEL, "kind": kind, "input": bad})
        assert_private(caught.value)
    good = {"model": MODEL, "kind": kind, "input": "a" * 64}
    assert check_request(good) == good


@pytest.mark.parametrize("kind", ["text", "param"])
def test_the_text_and_param_kinds_are_gone(kind: str) -> None:
    # CLS-006.3: the VisionBackend no longer embeds texts or exposes the logit params.
    with pytest.raises(RecordingError, match="not image or nsfw") as caught:
        check_request({"model": MODEL, "kind": kind, "input": SECRET})
    assert_private(caught.value)
    with pytest.raises(RecordingError, match="not image or nsfw"):
        vision_key(MODEL, kind, DIGEST)


@pytest.mark.parametrize(
    "request_body",
    [
        None,
        {"model": MODEL, "kind": "image"},
        {"model": MODEL, "kind": "image", "input": DIGEST, "label": "x"},
        {"model": "", "kind": "image", "input": DIGEST},
        {"model": MODEL, "kind": "caption", "input": DIGEST},
        {"model": MODEL, "kind": "image", "input": 3},
    ],
)
def test_a_bad_request_is_refused(request_body: object) -> None:
    with pytest.raises(RecordingError):
        check_request(request_body)


# --- the loader ---


def test_load_returns_the_array_and_hides_input_and_values(tmp_path: Path) -> None:
    # The file sits in a folder named by the planted SECRET: the loaded recording must not
    # carry the path, and a refused input that is SECRET itself must not be echoed.
    made = write_vision(tmp_path, MODEL, "image", DIGEST, np.array([0.25, 0.5]))
    path = tmp_path / SECRET / made.name
    path.parent.mkdir()
    path.write_bytes(made.read_bytes())
    recording = load_vision_recording(path, "recording pkg/x.json")
    assert recording.kind == "image" and recording.array.tolist() == [0.25, 0.5]
    # repr=False on every field keyed by the input (privacy checklist 4).
    for text in (repr(recording), str(recording)):
        assert SECRET not in text and DIGEST not in text and "0.25" not in text
    bad = raw_file(tmp_path, {"model": MODEL, "kind": "image", "input": SECRET}, encode_array(1.0))
    with pytest.raises(RecordingError) as caught:
        load_vision_recording(bad, "recording pkg/x.json")
    assert_private(caught.value)


def test_load_refuses_a_misnamed_tampered_or_odd_shaped_file(tmp_path: Path) -> None:
    good = write_vision(tmp_path, MODEL, "image", DIGEST, np.array([1.0]))
    renamed = good.with_name("0" * 64 + ".json")
    renamed.write_bytes(good.read_bytes())
    with pytest.raises(RecordingError, match="not named by the key") as caught:
        load_vision_recording(renamed, "recording pkg/0.json")
    assert_private(caught.value)
    bad_shape = write_vision(tmp_path, MODEL, "nsfw", "b" * 64, np.array([0.1, 0.2]))
    with pytest.raises(RecordingError, match="does not fit its kind"):
        load_vision_recording(bad_shape, "recording pkg/x.json")


@pytest.mark.parametrize("content", [b"{not json", b"\xff\xfe", b"[]", b'{"request": {}}'])
def test_load_refuses_a_malformed_file_privately(content: bytes, tmp_path: Path) -> None:
    path = tmp_path / "pkg" / f"{'a' * 64}.json"
    path.parent.mkdir()
    path.write_bytes(content)
    with pytest.raises(RecordingError) as caught:
        load_vision_recording(path, "recording pkg/x.json")
    assert_private(caught.value)


# --- the lint (TST-008.1.2) ---


def raw_file(root: Path, request: dict[str, Any], response: object) -> Path:
    """A file named by its request's key (when valid), holding whatever the test wants."""
    try:
        name = vision_key(request["model"], request["kind"], request["input"])
    except (RecordingError, KeyError, TypeError):
        name = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
    path = root / "pkg" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"request": request, "response": response}), encoding="utf-8")
    return path


def test_lint_accepts_every_kind(tmp_path: Path) -> None:
    write_vision(tmp_path, MODEL, "image", image_digest(block()), np.ones(4))
    write_vision(tmp_path, MODEL, "nsfw", image_digest(block()), np.float32(0.125))
    assert lint_recordings(tmp_path) == []


def test_lint_leaves_ollama_files_to_the_old_rules(tmp_path: Path) -> None:
    request = {"model": "m", "prompt": "p", "format": "json", "options": {}}
    path = tmp_path / "pkg" / f"{recording_key(request)}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"request": request, "response": {"response": "x"}}), encoding="utf-8"
    )
    write_vision(tmp_path, MODEL, "image", DIGEST, np.ones(2))
    assert lint_recordings(tmp_path) == []


def test_lint_reports_each_bad_vision_file_privately(tmp_path: Path) -> None:
    ok = encode_array(np.ones(2))
    bad = [
        ({"model": MODEL, "kind": "text", "input": f"{SECRET} folder/x.png"}, ok),
        ({"model": MODEL, "kind": "image", "input": SECRET}, ok),
        ({"model": MODEL, "kind": "param", "input": "logit_bias"}, encode_array(1.0)),
        ({"model": MODEL, "kind": "nsfw", "input": "a" * 64}, encode_array(np.ones(3))),
        ({"model": MODEL, "kind": "image", "input": DIGEST, "label": SECRET}, ok),
        ({"model": MODEL, "kind": "image", "input": "b" * 64}, {"shape": [2], "dtype": "float64"}),
    ]
    for request, response in bad:
        raw_file(tmp_path, request, response)
    problems = lint_recordings(tmp_path)
    assert len(problems) == len(bad)
    assert all(SECRET not in p and "x.png" not in p for p in problems)


def test_lint_refuses_a_tampered_or_misnamed_vision_file(tmp_path: Path) -> None:
    path = write_vision(tmp_path, MODEL, "image", DIGEST, np.ones(2))
    path.with_name("0" * 64 + ".json").write_bytes(path.read_bytes())
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["request"]["input"] = "b" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")
    problems = lint_recordings(tmp_path)
    assert len(problems) == 2 and all("not named by the key" in p for p in problems)


def test_lint_refuses_a_link(tmp_path: Path) -> None:
    good = write_vision(tmp_path, MODEL, "image", DIGEST, np.ones(2))
    link = tmp_path / "pkg" / ("2" * 64 + ".json")
    try:
        link.symlink_to(good)
    except OSError:
        pytest.fail("this host cannot create a symlink, so the link check cannot be tested")
    problems = lint_recordings(tmp_path)
    assert any("is a link" in p for p in problems) and all(SECRET not in p for p in problems)


@pytest.mark.parametrize("method", ["read_bytes", "is_symlink", "is_file"])
def test_lint_wraps_a_failing_filesystem_call(
    method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_vision(tmp_path, MODEL, "image", DIGEST, np.ones(2))

    def denied(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, method, denied)
    (problem,) = lint_recordings(tmp_path)
    assert str(tmp_path) not in problem and tmp_path.name not in problem


def test_the_committed_tree_lints_clean() -> None:
    assert lint_recordings() == []


# --- replay and record (TST-008.1.3) ---

TEST_ID = "tests/unit/pkg/test_x.py::test_y"


class FakeUpstream:
    """A stand-in for the real backend: deterministic vectors, a call counter, no model."""

    classifier_id = CLASSIFIER
    nsfw_id = NSFW

    def __init__(self, shift: float = 0.0) -> None:
        self.shift = shift
        self.calls = 0

    def embed_images(self, images: Any) -> np.ndarray:
        self.calls += 1
        return np.array([[i.getpixel((0, 0))[0] / 255, 0.5 + self.shift] for i in images])

    def nsfw_scores(self, images: Any) -> np.ndarray:
        self.calls += 1
        return np.array([0.125 + self.shift for _ in images])


def record_all(root: Path, upstream: FakeUpstream | None = None) -> RecordingVisionBackend:
    recorder = RecordingVisionBackend("pkg", upstream or FakeUpstream(), TEST_ID, root=root)
    recorder.embed_images([block(), block((10, 20, 30))])
    recorder.nsfw_scores([block()])
    return recorder


def replayer(root: Path) -> ReplayVisionBackend:
    return ReplayVisionBackend("pkg", TEST_ID, CLASSIFIER, NSFW, root=root)


def test_replay_serves_exactly_what_the_recorder_wrote(tmp_path: Path) -> None:
    upstream = FakeUpstream()
    record_all(tmp_path, upstream)
    replay = replayer(tmp_path)
    images = [block(), block((10, 20, 30))]
    assert (
        replay.embed_images(images).tobytes()
        == upstream.embed_images(images).astype(np.float32).tobytes()
    )
    assert replay.nsfw_scores([block()]).tolist() == [0.125]
    assert (replay.classifier_id, replay.nsfw_id) == (CLASSIFIER, NSFW)
    assert replay.failures == []
    assert lint_recordings(tmp_path) == []


def test_replay_returns_float32_arrays_of_the_right_shape(tmp_path: Path) -> None:
    record_all(tmp_path)
    replay = replayer(tmp_path)
    assert replay.embed_images([block(), block((10, 20, 30))]).shape == (2, 2)
    assert replay.embed_images([block()]).dtype == np.float32
    assert replay.nsfw_scores([block()]).shape == (1,)
    assert replay.embed_images([]).shape == (0, 0)


def test_a_miss_names_the_key_kind_and_test_and_nothing_else(tmp_path: Path) -> None:
    replay = replayer(tmp_path)
    with pytest.raises(RecordingError) as caught:
        replay.embed_images([named_block()])
    key = vision_key(CLASSIFIER, "image", image_digest(block()))
    message = str(caught.value)
    assert f"pkg/{key}.json" in message and "kind image" in message
    assert TEST_ID in message and "--record-vision" in message
    assert_private(caught.value)
    assert replay.failures == [message]


def test_each_miss_kind_is_a_tracked_failure(tmp_path: Path) -> None:
    replay = replayer(tmp_path)
    calls = [
        lambda: replay.embed_images([block()]),
        lambda: replay.nsfw_scores([block()]),
    ]
    for call in calls:
        with pytest.raises(RecordingError):
            call()
    assert len(replay.failures) == 2


def test_a_miss_escapes_except_exception(tmp_path: Path) -> None:
    replay = replayer(tmp_path)
    escaped = False
    try:
        try:
            replay.embed_images([block()])
        except Exception:  # a fail-closed caller
            pytest.fail("RecordingError was caught by except Exception")
    except RecordingError:
        escaped = True
    assert escaped and not issubclass(RecordingError, Exception)


def test_the_model_id_is_part_of_the_key(tmp_path: Path) -> None:
    record_all(tmp_path)
    other = ReplayVisionBackend("pkg", TEST_ID, "synthetic/other", NSFW, root=tmp_path)
    with pytest.raises(RecordingError):
        other.embed_images([block()])
    assert other.nsfw_scores([block()]).tolist() == [0.125]


def test_a_tampered_recording_fails_privately(tmp_path: Path) -> None:
    record_all(tmp_path)
    path = tmp_path / "pkg" / f"{vision_key(CLASSIFIER, 'image', image_digest(block()))}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["request"]["input"] = "b" * 64
    path.write_text(json.dumps(stored), encoding="utf-8")
    with pytest.raises(RecordingError, match="not named by the key") as caught:
        replayer(tmp_path).embed_images([block()])
    assert_private(caught.value)


def test_replay_refuses_a_path_like_model_id_without_looking_it_up(tmp_path: Path) -> None:
    replay = ReplayVisionBackend("pkg", TEST_ID, f"folder/{SECRET}.png", NSFW, root=tmp_path)
    with pytest.raises(RecordingError) as caught:
        replay.embed_images([block()])
    assert "is not one of the vision models" in str(caught.value)
    assert_private(caught.value)


def test_a_broken_image_fails_with_fixed_text(tmp_path: Path) -> None:
    class Broken:
        mode = "RGB"
        size = (1, 1)

        def seek(self, frame: int) -> None:
            raise OSError(f"cannot read /host/{SECRET}.png")

    with pytest.raises(RecordingError) as caught:
        replayer(tmp_path).embed_images([Broken()])  # type: ignore[list-item]
    assert_private(caught.value)


def test_backends_hide_inputs_in_repr(tmp_path: Path) -> None:
    replay, recorder = (
        replayer(tmp_path),
        RecordingVisionBackend("pkg", FakeUpstream(), TEST_ID, root=tmp_path),
    )
    with pytest.raises(RecordingError):
        replay.embed_images([named_block()])
    for backend in (replay, recorder):
        assert SECRET not in repr(backend) and SECRET not in str(backend)
    recorder.embed_images([named_block()])
    assert SECRET not in repr(recorder)


def test_record_keeps_an_existing_recording_within_the_tolerance(tmp_path: Path) -> None:
    record_all(tmp_path)
    before = {p.name: p.read_bytes() for p in (tmp_path / "pkg").iterdir()}
    close = FakeUpstream(shift=TOLERANCE / 2)
    record_all(tmp_path, close)
    assert {p.name: p.read_bytes() for p in (tmp_path / "pkg").iterdir()} == before


def test_record_refuses_a_different_answer_and_names_the_key(tmp_path: Path) -> None:
    record_all(tmp_path)
    before = {p.name: p.read_bytes() for p in (tmp_path / "pkg").iterdir()}
    upstream = FakeUpstream(shift=TOLERANCE * 10)
    far = RecordingVisionBackend("pkg", upstream, TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError, match="different answer") as caught:
        far.embed_images([block()])
    assert vision_key(CLASSIFIER, "image", image_digest(block())) in str(caught.value)
    assert TEST_ID in str(caught.value) and len(far.failures) == 1
    assert_private(caught.value)
    assert {p.name: p.read_bytes() for p in (tmp_path / "pkg").iterdir()} == before


def test_record_refuses_inputs_the_lint_would_refuse(tmp_path: Path) -> None:
    class Local(FakeUpstream):
        classifier_id = f"C:/Users/{SECRET}.png"

    recorder = RecordingVisionBackend("pkg", Local(), TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError) as caught:
        recorder.embed_images([named_block()])
    assert_private(caught.value)
    assert not (tmp_path / "pkg").exists()


@pytest.mark.parametrize("bad", ["rows", "scores"])
def test_record_refuses_an_upstream_answer_of_the_wrong_size(bad: str, tmp_path: Path) -> None:
    class Wrong(FakeUpstream):
        def embed_images(self, images: Any) -> np.ndarray:
            return np.zeros((len(images) + 1, 2))

        def nsfw_scores(self, images: Any) -> np.ndarray:
            return np.zeros((len(images), 2))

    recorder = RecordingVisionBackend("pkg", Wrong(), TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError) as caught:
        recorder.embed_images([block()]) if bad == "rows" else recorder.nsfw_scores([block()])
    assert_private(caught.value)
    assert not (tmp_path / "pkg").exists()


@pytest.mark.parametrize("method", ["is_file", "mkdir", "write_bytes", "read_bytes"])
def test_record_reports_a_failing_filesystem_call_by_key(
    method: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if method == "read_bytes":
        record_all(tmp_path)  # an existing file is what gets read
    recorder = RecordingVisionBackend("pkg", FakeUpstream(), TEST_ID, root=tmp_path)

    def denied(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, method, denied)
    with pytest.raises(RecordingError) as caught:
        recorder.embed_images([block()])
    assert str(tmp_path) not in str(caught.value) and tmp_path.name not in str(caught.value)
    assert_private(caught.value)
    assert len(recorder.failures) == 1


def test_replay_reports_a_failing_stat_by_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    record_all(tmp_path)

    def denied(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, "is_file", denied)
    with pytest.raises(RecordingError) as caught:
        replayer(tmp_path).nsfw_scores([block()])
    assert str(tmp_path) not in str(caught.value) and tmp_path.name not in str(caught.value)
    assert_private(caught.value)


# --- conformance to the real protocol (MOD-002.D1) ---


def test_both_backends_satisfy_the_real_vision_backend_protocol(tmp_path: Path) -> None:
    assert isinstance(replayer(tmp_path), VisionBackend)
    recorder = RecordingVisionBackend("pkg", FakeUpstream(), TEST_ID, root=tmp_path)
    assert isinstance(recorder, VisionBackend)


# --- the shared fixture (tests/conftest.py), run in a synthetic tree with pytester ---

pytest_plugins = ["pytester"]

REPO_TESTS = Path(__file__).resolve().parents[1]
INNER_SECRET = "zzinner" + "secretqx"  # never written whole into the inner sources
INNER_UNIT = """
from PIL import Image
from tests.recordings.vision_backend import ReplayVisionBackend

NAME = "zzinner" + "secretqx"


def test_replays(vision_backend, extra_vision_models):
    extra_vision_models("synthetic/c", "synthetic/n")
    assert isinstance(vision_backend("models", "synthetic/c", "synthetic/n"), ReplayVisionBackend)


def test_miss(vision_backend, extra_vision_models):
    extra_vision_models("synthetic/c", "synthetic/n")
    image = Image.new("RGB", (3, 3))
    image.filename = "/host/" + NAME + ".png"
    vision_backend("models", "synthetic/c", "synthetic/n").embed_images([image])


def test_swallowed(vision_backend, extra_vision_models):
    extra_vision_models("synthetic/c", "synthetic/n")
    try:
        backend = vision_backend("models", "synthetic/c", "synthetic/n")
        backend.embed_images([Image.new("RGB", (2, 2))])
    except BaseException:
        pass
"""
INNER_GPU = """
import pytest
from tests.recordings.vision_backend import RecordingVisionBackend


class Upstream:
    classifier_id = "c"
    nsfw_id = "n"


def test_upstream(vision_backend, pytestconfig):
    backend = vision_backend("models", upstream=Upstream())
    if pytestconfig.getoption("--record-vision"):
        assert isinstance(backend, RecordingVisionBackend)
    else:
        assert type(backend) is Upstream


def test_needs_upstream(vision_backend):
    with pytest.raises(BaseException):
        vision_backend("models")
"""


@pytest.fixture
def inner(pytester: pytest.Pytester) -> pytest.Pytester:
    """A copy of the real conftest and helpers, with one unit and one gpu module."""
    tests = pytester.path / "tests"
    (tests / "recordings").mkdir(parents=True)
    (tests / "unit").mkdir()
    (tests / "gpu").mkdir()
    (pytester.path / "config.yaml").write_text(
        (REPO_TESTS.parent / "config.yaml").read_text(encoding="utf-8"), encoding="utf-8"
    )
    for rel in (
        "conftest.py",
        "recordings/replay.py",
        "recordings/vision.py",
        "recordings/vision_backend.py",
    ):
        (tests / rel).write_text((REPO_TESTS / rel).read_text(encoding="utf-8"), encoding="utf-8")
    (tests / "unit" / "test_inner_unit.py").write_text(INNER_UNIT, encoding="utf-8")
    (tests / "gpu" / "test_inner_gpu.py").write_text(INNER_GPU, encoding="utf-8")
    return pytester


def run_inner(inner: pytest.Pytester, *args: str) -> pytest.RunResult:
    return inner.runpytest_subprocess(
        "--import-mode=importlib", "-p", "no:cacheprovider", "--tb=short", "-rA", *args
    )


def test_fixture_replays_outside_gpu_and_fails_each_miss_once(inner: pytest.Pytester) -> None:
    result = run_inner(inner, "-m", "not gpu")
    # test_swallowed: its call passes, and its teardown reports the miss as an error.
    result.assert_outcomes(passed=2, failed=1, errors=1)
    output = result.stdout.str() + result.stderr.str()
    key = vision_key("synthetic/c", "image", image_digest(Image.new("RGB", (3, 3))))
    assert f"no recording models/{key}.json" in output
    assert "tests/unit/test_inner_unit.py::test_miss" in output
    assert "Vision recording failure caught by the code under test" in output
    assert "tests/unit/test_inner_unit.py::test_swallowed" in output
    assert INNER_SECRET not in output


def test_fixture_gives_back_the_real_backend_in_gpu(inner: pytest.Pytester) -> None:
    run_inner(inner, "-m", "gpu").assert_outcomes(passed=2)


def test_fixture_records_in_gpu_with_the_option(inner: pytest.Pytester) -> None:
    run_inner(inner, "-m", "gpu", "--record-vision").assert_outcomes(passed=2)


def test_vision_record_option_is_refused_when_other_tiers_are_selected(
    inner: pytest.Pytester,
) -> None:
    result = run_inner(inner, "--record-vision")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--record-vision is for the gpu tier only*"])


def truncated_png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (10, 200, 30)).save(buffer, format="PNG")
    data = buffer.getvalue()
    return data[: len(data) // 2]


def test_a_truncated_image_digest_error_is_unchained() -> None:
    # TST-009.1.6: a valid header with cut-off pixel data. The library error must be on
    # neither __cause__ nor __context__ (it can embed a name).
    with Image.open(io.BytesIO(truncated_png())) as image:
        with pytest.raises(RecordingError) as caught:
            image_digest(image)
    assert str(caught.value) == "an image could not be decoded for a vision key"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_a_truncated_request_image_is_refused_unchained() -> None:
    cut = base64.b64encode(truncated_png()).decode("ascii")
    request = dict(model="m", prompt="Name the colour", format=dict(), options=dict(), images=[cut])
    with pytest.raises(RecordingError) as caught:
        recording_key(request)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
