"""TST-008.1: the vision recording format, replay, recorder and lint (TST-008.D3, D7).

Unit tier: every image is synthetic and generated here, every recording lives under `tmp_path`,
and no model is loaded. The planted SECRET stands in for a text input that must never appear in
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

from tests.recordings.replay import RecordingError, lint_recordings, recording_key
from tests.recordings.vision import (
    check_request,
    decode_array,
    encode_array,
    image_digest,
    load_vision_recording,
    vision_key,
)

MODEL = "synthetic/vision-model"
SECRET = "zz-planted-secret-qx"

# A copy of every default prompt in DESIGN.md §4.3 (both tables). CLS-002.2 records replays with
# these, so the text lint must accept all of them.
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
    text = '{"input":"p","kind":"text","model":"m"}'
    assert vision_key("m", "text", "p") == hashlib.sha256(text.encode()).hexdigest()


def test_key_is_pinned() -> None:
    # Hand-computed once; a change here means every committed recording must be re-keyed.
    assert (
        vision_key("m", "text", "p")
        == "61f11ba7fde6fed85d2243362df41d8bba8fc4f6961c172f033a0ef132465418"
    )


@pytest.mark.parametrize("field", ["model", "kind", "input"])
def test_every_field_changes_the_key(field: str) -> None:
    base = {"model": "m", "kind": "text", "input": "p"}
    other = {**base, field: "nsfw" if field == "kind" else "other"}
    assert vision_key(**base) != vision_key(**other)


def test_non_ascii_is_hashed_as_utf8_not_escaped() -> None:
    text = json.dumps(
        {"model": "m", "kind": "text", "input": "café – 東京"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert vision_key("m", "text", "café – 東京") == hashlib.sha256(text.encode()).hexdigest()


def test_lone_surrogate_and_unknown_kind_fail_without_echoing() -> None:
    with pytest.raises(RecordingError) as caught:
        vision_key("m", "text", f"{SECRET}\ud800")
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


# --- the text input rule ---


@pytest.mark.parametrize("prompt", DESIGN_PROMPTS)
def test_every_design_seed_prompt_is_accepted(prompt: str) -> None:
    write = {"model": MODEL, "kind": "text", "input": prompt}
    assert check_request(write) == write


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
    ],
)
def test_path_like_or_unprintable_text_is_refused(text: str) -> None:
    with pytest.raises(RecordingError) as caught:
        check_request({"model": MODEL, "kind": "text", "input": text})
    assert_private(caught.value)


def test_a_plain_slash_between_words_is_fine() -> None:
    request = {"model": MODEL, "kind": "text", "input": "a photo and/or a drawing"}
    assert check_request(request) == request


@pytest.mark.parametrize("kind", ["image", "nsfw"])
def test_an_image_or_nsfw_input_must_be_a_hash(kind: str) -> None:
    for bad in (SECRET, "ABC" * 22, "a" * 63, "/a/b.png"):
        with pytest.raises(RecordingError) as caught:
            check_request({"model": MODEL, "kind": kind, "input": bad})
        assert_private(caught.value)
    good = {"model": MODEL, "kind": kind, "input": "a" * 64}
    assert check_request(good) == good


def test_param_inputs_are_the_two_logit_names() -> None:
    for name in ("logit_scale", "logit_bias"):
        check_request({"model": MODEL, "kind": "param", "input": name})
    with pytest.raises(RecordingError):
        check_request({"model": MODEL, "kind": "param", "input": "temperature"})


@pytest.mark.parametrize(
    "request_body",
    [
        None,
        {"model": MODEL, "kind": "text"},
        {"model": MODEL, "kind": "text", "input": "p", "label": "x"},
        {"model": "", "kind": "text", "input": "p"},
        {"model": MODEL, "kind": "caption", "input": "p"},
        {"model": MODEL, "kind": "text", "input": 3},
    ],
)
def test_a_bad_request_is_refused(request_body: object) -> None:
    with pytest.raises(RecordingError):
        check_request(request_body)


# --- the loader ---


def test_load_returns_the_array_and_hides_input_and_values(tmp_path: Path) -> None:
    path = write_vision(tmp_path, MODEL, "text", f"{SECRET} prompt", np.array([0.25, 0.5]))
    recording = load_vision_recording(path, "recording pkg/x.json")
    assert recording.kind == "text" and recording.array.tolist() == [0.25, 0.5]
    # repr=False on every field keyed by the input (privacy checklist 4).
    assert SECRET not in repr(recording) and SECRET not in str(recording)
    assert "0.25" not in repr(recording)


def test_load_refuses_a_misnamed_tampered_or_odd_shaped_file(tmp_path: Path) -> None:
    good = write_vision(tmp_path, MODEL, "text", "alpha", np.array([1.0]))
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
    write_vision(tmp_path, MODEL, "text", "a photo of a cat", np.ones(4))
    write_vision(tmp_path, MODEL, "image", image_digest(block()), np.ones(4))
    write_vision(tmp_path, MODEL, "nsfw", image_digest(block()), np.float32(0.125))
    write_vision(tmp_path, MODEL, "param", "logit_scale", np.float32(117.0))
    write_vision(tmp_path, MODEL, "param", "logit_bias", np.float32(-16.5))
    assert lint_recordings(tmp_path) == []


def test_lint_leaves_ollama_files_to_the_old_rules(tmp_path: Path) -> None:
    request = {"model": "m", "prompt": "p", "format": "json", "options": {}}
    path = tmp_path / "pkg" / f"{recording_key(request)}.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"request": request, "response": {"response": "x"}}), encoding="utf-8"
    )
    write_vision(tmp_path, MODEL, "text", "alpha", np.ones(2))
    assert lint_recordings(tmp_path) == []


def test_lint_reports_each_bad_vision_file_privately(tmp_path: Path) -> None:
    ok = encode_array(np.ones(2))
    bad = [
        ({"model": MODEL, "kind": "text", "input": f"{SECRET} folder/x.png"}, ok),
        ({"model": MODEL, "kind": "image", "input": SECRET}, ok),
        ({"model": MODEL, "kind": "param", "input": "temperature"}, encode_array(1.0)),
        ({"model": MODEL, "kind": "nsfw", "input": "a" * 64}, encode_array(np.ones(3))),
        ({"model": MODEL, "kind": "text", "input": "alpha", "label": SECRET}, ok),
        ({"model": MODEL, "kind": "text", "input": "beta"}, {"shape": [2], "dtype": "float64"}),
    ]
    for request, response in bad:
        raw_file(tmp_path, request, response)
    problems = lint_recordings(tmp_path)
    assert len(problems) == len(bad)
    assert all(SECRET not in p and "x.png" not in p for p in problems)


def test_lint_refuses_a_tampered_or_misnamed_vision_file(tmp_path: Path) -> None:
    path = write_vision(tmp_path, MODEL, "text", "alpha", np.ones(2))
    path.with_name("0" * 64 + ".json").write_bytes(path.read_bytes())
    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["request"]["input"] = "beta"
    path.write_text(json.dumps(stored), encoding="utf-8")
    problems = lint_recordings(tmp_path)
    assert len(problems) == 2 and all("not named by the key" in p for p in problems)


def test_lint_refuses_a_link(tmp_path: Path) -> None:
    good = write_vision(tmp_path, MODEL, "text", "alpha", np.ones(2))
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
    write_vision(tmp_path, MODEL, "text", "alpha", np.ones(2))

    def denied(self: Path, *args: Any, **kwargs: Any) -> Any:
        raise PermissionError(13, "Permission denied", str(self))

    monkeypatch.setattr(Path, method, denied)
    (problem,) = lint_recordings(tmp_path)
    assert str(tmp_path) not in problem and tmp_path.name not in problem


def test_the_committed_tree_lints_clean() -> None:
    assert lint_recordings() == []
