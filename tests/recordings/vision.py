"""TST-008.1: the vision recording format, the key and the array codec (TST-008.D3, D7).

One JSON file per request, `tests/recordings/<package>/<key>.json`:

    {"request": {"model": ..., "kind": "image"|"text"|"nsfw"|"param", "input": ...},
     "response": {"shape": [...], "dtype": "float32", "data": "<base64 little-endian>"}}

The key is the SHA-256 of `json.dumps({model, kind, input}, sort_keys=True, separators=(",", ":"),
ensure_ascii=False)` in UTF-8. `input` is a text's string, or, for `image` and `nsfw`, the digest
of the decoded first frame (`image_digest`): never a path or a file name. A `param` (D7) is
`logit_scale` or `logit_bias`, with a scalar shape.

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

KINDS = ("image", "text", "nsfw", "param")
PARAMS = ("logit_scale", "logit_bias")
REQUEST_FIELDS = {"model", "kind", "input"}
RESPONSE_FIELDS = {"shape", "dtype", "data"}
DTYPE = "float32"
HASH_RE = re.compile(r"[0-9a-f]{64}")
# Lint bounds: a recording holds an embedding or a score, never a pixel dump.
MAX_ELEMENTS = 4096
MAX_RANK = 2
MAX_TEXT_CHARS = 256
# TST-008.1.5: a text input is an allowlist of shapes, not a blacklist of path shapes. Only ASCII
# letters, digits, spaces and , ' - ( ) . pass; a "." only as sentence punctuation (never between
# two letters or digits, so no file extension); and no camera-stem token (letters, then "-" or
# digits). The DESIGN §4.3 prompts all pass.
_TEXT_CHARS = re.compile(r"[A-Za-z0-9 ,'()\-.]+")
_DOT_INSIDE_WORD = re.compile(r"[A-Za-z0-9]\.[A-Za-z0-9]")
_STEM_TOKEN = re.compile(r"[A-Za-z]+-\d+|[A-Za-z]{2,}\d{3,}")
_TOKEN_SPLIT = re.compile(r"[ ,'().]+")
# A Hugging Face repo id (owner/name): the model field must never carry a local path.
MODEL_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}/[A-Za-z0-9][A-Za-z0-9._-]{0,95}")
TEXT_RULE = (
    "a vision text input may hold only ASCII letters, digits, spaces and , ' - ( ) . "
    "with no dot inside a word and no file-stem token"
)


def _fixed(text: str) -> RecordingError:
    return RecordingError(text)


def vision_key(model: str, kind: str, input: str) -> str:
    """The SHA-256 hex digest of the canonical request: a recording's file name (D3)."""
    if kind not in KINDS:
        raise _fixed("a vision recording kind is not image, text, nsfw or param")
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
    except (OSError, EOFError, ValueError, AttributeError, UnicodeEncodeError):
        # The library's message can embed a file name, so it is not chained.
        raise _fixed("an image could not be decoded for a vision key") from None
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


def check_text_input(text: str) -> None:
    """A text input must pass the allowlist `TEXT_RULE` (TST-008.1.5).

    The lint can't prove a string is synthetic. The allowlist keeps out the shapes of a path,
    a file name and a camera stem; the review checks the rest. The DESIGN §4.3 prompts all pass
    (a test holds a copy).
    """
    if not text or len(text) > MAX_TEXT_CHARS:
        raise _fixed("a vision text input is empty or longer than 256 characters")
    if (
        not _TEXT_CHARS.fullmatch(text)
        or _DOT_INSIDE_WORD.search(text)
        or any(_STEM_TOKEN.fullmatch(token) for token in _TOKEN_SPLIT.split(text))
    ):
        raise _fixed(TEXT_RULE)


def check_model_id(model: object) -> str:
    """A model id is a Hugging Face repo id, `owner/name`: never a path (TST-008.1.5)."""
    if not isinstance(model, str) or not MODEL_ID_RE.fullmatch(model) or ".." in model:
        raise _fixed("a vision model id must be a repo id such as owner/name, never a path")
    return model


def check_request(request: object) -> dict[str, str]:
    """A request, checked against the format. The `param` inputs are fixed (D7)."""
    if not isinstance(request, Mapping) or set(request) != REQUEST_FIELDS:
        raise _fixed("a vision request must hold exactly model, kind and input")
    model, kind, value = request["model"], request["kind"], request["input"]
    model = check_model_id(model)
    if not isinstance(value, str):
        raise _fixed("a vision request holds a non-text input")
    if kind not in KINDS:
        raise _fixed("a vision recording kind is not image, text, nsfw or param")
    if kind in ("image", "nsfw") and not HASH_RE.fullmatch(value):
        raise _fixed("an image input must be a 64-hex digest, never a path")
    if kind == "param" and value not in PARAMS:
        raise _fixed("a param input must be logit_scale or logit_bias")
    if kind == "text":
        check_text_input(value)
    return {"model": model, "kind": kind, "input": value}


def expected_shape_ok(kind: str, shape: tuple[int, ...]) -> bool:
    """`param` and `nsfw` are scalars; an `image` or `text` embedding is a 1-D vector."""
    if kind in ("param", "nsfw"):
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
    "PARAMS",
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
