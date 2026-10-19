"""TST-008.1: the vision recording format, the key and the array codec (TST-008.D3).

One JSON file per request, `tests/recordings/<package>/<key>.json`:

    {"request": {"model": ..., "kind": "image"|"nsfw", "input": ...},
     "response": {"shape": [...], "dtype": "float32", "data": "<base64 little-endian>"}}

The key is the SHA-256 of `json.dumps({model, kind, input}, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` in UTF-8. `input` is the digest of the decoded first frame
(`image_digest`): never a path or a file name.

Privacy (DOC-007.D1): recordings come from synthetic inputs only. Every error is fixed text that
names at most the package, the 64-hex key, the kind and the test id, and is raised unchained.
"""

import base64
import binascii
import hashlib
import json
import math
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from tests.recordings.replay import RECORDINGS, RecordingError

KINDS = ("image", "nsfw")
REQUEST_FIELDS = {"model", "kind", "input"}
RESPONSE_FIELDS = {"shape", "dtype", "data"}
DTYPE = "float32"
HASH_RE = re.compile(r"[0-9a-f]{64}")
# Lint bounds: a recording holds an embedding or a score, never a pixel dump.
MAX_ELEMENTS = 4096
MAX_RANK = 2
MAX_TEXT_CHARS = 256
# TST-008.D9: a prompt text (a rendered slot, an image request's prompt; no vision recording
# holds text any more, CLS-006.3) is limited to the characters the DESIGN §4.3 prompts use: ASCII
# letters, digits, single spaces, comma and apostrophe. No "." and none of ( ) - _ / \ ~ :.
# No word (split on spaces and commas) holds 3 or more digits. At most 256 characters, no
# leading or trailing space, at least one letter.
_TEXT_CHARS = re.compile(r"[A-Za-z0-9 ,']+")
_TOKEN_SPLIT = re.compile(r"[ ,]+")
MAX_WORD_DIGITS = 2
TEXT_RULE = (
    "a vision text input may hold only ASCII letters, digits, single spaces, commas and "
    "apostrophes, no leading or trailing space, and no word with 3 or more digits"
)
# TST-008.D9: a model id must be one of the ids in config.yaml's models section that the vision
# backend uses (models.classifier and models.nsfw). A test may register extra ids, but only with
# the fixed owner "synthetic" (TST-008.1.7); no other shape is ever accepted.
CONFIG_FILE = Path(__file__).resolve().parents[2] / "config.yaml"
TEST_MODEL_RE = re.compile(r"synthetic/[a-z0-9-]{1,40}")
_test_models: set[str] = set()


def _fixed(text: str) -> RecordingError:
    return RecordingError(text)


def vision_key(model: str, kind: str, input: str) -> str:
    """The SHA-256 hex digest of the canonical request: a recording's file name (D3)."""
    if kind not in KINDS:
        raise _fixed("a vision recording kind is not image or nsfw")
    if not isinstance(model, str) or not isinstance(input, str):
        raise _fixed("a vision recording request holds a non-text model or input")
    text = json.dumps(
        {"model": model, "kind": kind, "input": input},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate: the error would quote the text, so it is not chained.
        raise _fixed("the vision request is not valid UTF-8 text") from None
    return hashlib.sha256(data).hexdigest()


def image_digest(image: Image.Image) -> str:
    """SHA-256 of the decoded first frame: `mode`, `size` and `tobytes()` (D3).

    The fields are length-prefixed, so no pixel data can be mistaken for the mode or the size.
    A multi-frame image is seen as its first frame only.
    """
    try:
        image.seek(0)
        mode = image.mode.encode("ascii")
        width, height = image.size
        pixels = image.tobytes()
        decoded = True
    except (OSError, EOFError, ValueError, AttributeError, UnicodeEncodeError):
        decoded = False
    if not decoded:
        # Raised outside the except block, so the library's message (it can embed a file
        # name) is on neither __cause__ nor __context__.
        raise _fixed("an image could not be decoded for a vision key")
    digest = hashlib.sha256()
    for part in (mode, struct.pack("<QQ", width, height), pixels):
        digest.update(struct.pack("<Q", len(part)))
        digest.update(part)
    return digest.hexdigest()


def encode_array(array: Any) -> dict[str, Any]:
    """A float array as the response: `{"shape", "dtype", "data"}`, little-endian float32."""
    values = np.asarray(array, dtype=np.float32)
    if not bool(np.isfinite(values).all()):
        raise _fixed("a vision array holds a value that is not finite")
    data = np.ascontiguousarray(values, dtype="<f4").tobytes()
    return {
        "shape": [int(n) for n in values.shape],
        "dtype": DTYPE,
        "data": base64.b64encode(data).decode("ascii"),
    }


def check_response(response: object) -> tuple[tuple[int, ...], bytes]:
    """The shape and the raw bytes of a response, or a `RecordingError` with fixed text."""
    if not isinstance(response, Mapping) or set(response) != RESPONSE_FIELDS:
        raise _fixed("a vision response must hold exactly shape, dtype and data")
    if response["dtype"] != DTYPE:
        raise _fixed("a vision response dtype must be float32")
    shape = response["shape"]
    if (
        not isinstance(shape, list)
        or len(shape) > MAX_RANK
        or not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in shape)
    ):
        raise _fixed("a vision response shape is not a short list of sizes")
    count = math.prod(shape)
    if count > MAX_ELEMENTS:
        raise _fixed("a vision response is larger than an embedding")
    if not isinstance(response["data"], str):
        raise _fixed("a vision response data is not base64 text")
    try:
        raw = base64.b64decode(response["data"].encode("ascii"), validate=True)
    except (binascii.Error, UnicodeEncodeError, ValueError):
        raise _fixed("a vision response data is not strict base64") from None
    if len(raw) != 4 * count:
        raise _fixed("a vision response data does not match its shape")
    if not bool(np.isfinite(np.frombuffer(raw, dtype="<f4")).all()):
        raise _fixed("a vision array holds a value that is not finite")
    return tuple(shape), raw


def decode_array(response: object) -> np.ndarray:
    """The read-only float32 array of a response; the bytes round-trip exactly."""
    shape, raw = check_response(response)
    array = np.frombuffer(raw, dtype="<f4").astype(np.float32).reshape(shape)
    array.setflags(write=False)
    return array


def _digits(word: str) -> int:
    return sum(char.isdigit() for char in word)


def check_text_input(text: str) -> None:
    """A prompt text must pass the allowlist `TEXT_RULE` (TST-008.1.5).

    The lint can't prove a string is synthetic. The rule is the character set the DESIGN §4.3
    prompts use, and nothing more: ASCII letters, digits, single spaces, comma and apostrophe,
    no leading or trailing space, no word of 3 or more digits (TST-008.D9). The review checks
    the rest. The DESIGN §4.3 prompts all pass (a test holds a copy).
    """
    if not text or len(text) > MAX_TEXT_CHARS:
        raise _fixed("a vision text input is empty or longer than 256 characters")
    if (
        not _TEXT_CHARS.fullmatch(text)
        or "  " in text
        or text != text.strip(" ")
        or not any(char.isalpha() for char in text)
        or any(_digits(word) > MAX_WORD_DIGITS for word in _TOKEN_SPLIT.split(text))
    ):
        raise _fixed(TEXT_RULE)


def config_models() -> frozenset[str]:
    """`models.classifier` and `models.nsfw` from the committed config.yaml (TST-008.D9)."""
    from classifier.config import load_config

    try:
        models = load_config(CONFIG_FILE).models
        return frozenset((models.classifier, models.nsfw))
    except Exception:
        pass  # the loader's message names a path or quotes the file: raised below, unchained
    raise _fixed("config.yaml could not be read for the vision model ids")


def register_test_model(model: str) -> None:
    """Allow one extra synthetic id for a test; pair with `unregister_test_model` (fixture)."""
    if not isinstance(model, str) or not TEST_MODEL_RE.fullmatch(model):
        raise _fixed("a test model id must be synthetic/ followed by 1 to 40 of a-z, 0-9 and -")
    _test_models.add(model)


def unregister_test_model(model: str) -> None:
    _test_models.discard(model)


def check_model_id(model: object) -> str:
    """A model id must be one of the config.yaml vision models, or a registered test id."""
    if not isinstance(model, str) or model not in config_models() | _test_models:
        raise _fixed("a vision model id is not one of the vision models in config.yaml")
    return model


def check_request(request: object) -> dict[str, str]:
    """A request, checked against the format."""
    if not isinstance(request, Mapping) or set(request) != REQUEST_FIELDS:
        raise _fixed("a vision request must hold exactly model, kind and input")
    model, kind, value = request["model"], request["kind"], request["input"]
    model = check_model_id(model)
    if not isinstance(value, str):
        raise _fixed("a vision request holds a non-text input")
    if kind not in KINDS:
        raise _fixed("a vision recording kind is not image or nsfw")
    if not HASH_RE.fullmatch(value):
        raise _fixed("an image input must be a 64-hex digest, never a path")
    return {"model": model, "kind": kind, "input": value}


def expected_shape_ok(kind: str, shape: tuple[int, ...]) -> bool:
    """An `nsfw` score is a scalar; an `image` embedding is a 1-D vector."""
    if kind == "nsfw":
        return shape == ()
    return len(shape) == 1 and shape[0] > 0


@dataclass(frozen=True)
class VisionRecording:
    """A loaded recording. The input and the array are keyed by the request: not in a repr."""

    model: str = field(repr=False)
    kind: str
    input: str = field(repr=False)
    array: np.ndarray = field(repr=False)


def load_vision_recording(path: Path, where: str) -> VisionRecording:
    """A vision recording file, checked; its name must be its request's key."""
    try:
        data = path.read_bytes()
    except OSError:
        # The OSError's text carries the full path, so it is not chained (PR #71).
        raise _fixed(f"{where} cannot be read as a file") from None
    try:
        recording = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise _fixed(f"{where} is not UTF-8 JSON") from None
    if not isinstance(recording, dict) or set(recording) != {"request", "response"}:
        raise _fixed(f"{where} must hold exactly the keys request and response")
    try:
        request = check_request(recording["request"])
        array = decode_array(recording["response"])
        key = vision_key(request["model"], request["kind"], request["input"])
    except RecordingError as exc:
        # Re-labelled with the file; the library-free text is already fixed.
        problem = str(exc)
        raise _fixed(f"{where}: {problem}") from None
    if key != path.stem:
        raise _fixed(f"{where} is not named by the key of its stored request")
    if not expected_shape_ok(request["kind"], array.shape):
        raise _fixed(f"{where} has a shape that does not fit its kind")
    return VisionRecording(request["model"], request["kind"], request["input"], array)


def is_vision_request(request: object) -> bool:
    """A stored request with a `kind` is a vision recording; otherwise it is TST-005's."""
    return isinstance(request, Mapping) and "kind" in request


__all__ = [
    "KINDS",
    "RECORDINGS",
    "VisionRecording",
    "check_request",
    "check_response",
    "decode_array",
    "encode_array",
    "image_digest",
    "is_vision_request",
    "load_vision_recording",
    "vision_key",
]
