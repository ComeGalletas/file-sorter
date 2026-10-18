"""TST-005.1: replay recorded Ollama responses outside the `gpu` tier (CLAUDE.md §3).

Format (TST-005.D3, D5): one JSON file per request, `tests/recordings/<package>/<key>.json`,
holding `{"request": <the /api/generate body as sent>, "response": <Ollama's JSON reply>}`.
The key is the SHA-256 of the canonical request: `json.dumps` of `model`, `prompt`, `format`
and `options`, plus `think` and `raw` only when the body carries them, with `sort_keys=True`,
`separators=(",", ":")`, `ensure_ascii=False`, encoded as UTF-8. `keep_alive` and `stream`
are not part of the key.

A request that carries `images` (TST-009.D2) also keys `image_digests`: the TST-008.D8 digest of
each decoded image, in order. The recording stores that list in place of `images`, so no pixel or
base64 data ever reaches disk, and the prompt of such a request must pass TST-008.D9's text rule.

`ReplayTransport` serves those files to `OllamaClient(host, transport=...)` and never opens a
socket. `RecordingTransport` (record mode, `gpu` tier only) forwards to an upstream transport
that the caller builds, and writes the files. The shared `ollama_transport` fixture in
tests/conftest.py picks between them.

Privacy (SAN-001.D10, DOC-007.D1): recordings come from synthetic strings only. Every error
names at most the package, the 64-hex key and the test id, never a prompt, schema or answer,
and is raised unchained.
"""

import base64
import hashlib
import io
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import httpx

from classifier.models.ollama import OllamaError, check_host

RECORDINGS = Path(__file__).resolve().parent
GENERATE_PATH = "/api/generate"
# TST-005.D5: always keyed, and keyed only when the body carries them.
KEYED_FIELDS = ("model", "prompt", "format", "options")
OPTIONAL_KEYED_FIELDS = ("think", "raw")
# TST-009.D2: a request with images is keyed by their digests, within these limits.
IMAGES_FIELD = "images"
DIGESTS_FIELD = "image_digests"
MAX_IMAGES = 8
MAX_IMAGE_BYTES = 8 * 1024 * 1024  # decoded bytes of one image, as sent
MAX_IMAGE_PIXELS = 16_000_000  # width x height, checked before any pixel is decoded
IMAGE_REFUSED = "a request image is not a base64 image within the recording limits"
# A stored request that carries image digests holds only these fields.
IMAGE_REQUEST_FIELDS = {
    *KEYED_FIELDS,
    *OPTIONAL_KEYED_FIELDS,
    "keep_alive",
    "stream",
    DIGESTS_FIELD,
}
RECORDING_FIELDS = {"request", "response"}
# Ollama's token ids of the prompt: bulky, and unused by OllamaClient. Not recorded.
UNRECORDED_RESPONSE_FIELDS = ("context",)
PACKAGE_RE = re.compile(r"[a-z][a-z0-9_]*")
KEY_RE = re.compile(r"[0-9a-f]{64}")
RECORD_HINT = "record it in the gpu tier: pytest -m gpu --record-ollama <test path>"


class RecordingError(BaseException):
    """A replay or record failure: a missing, malformed or mismatched recording.

    A `BaseException`, like `pytest.fail`, so `OllamaClient`'s `httpx` error handling and a
    fail-closed `except Exception` in the code under test cannot turn it into a pass.
    """


def _image_digest(encoded: object) -> str:
    """The TST-008.D8 digest of one base64 image of a live body, decoded in memory only."""
    from PIL import Image

    from tests.recordings.vision import image_digest

    digest = None
    if isinstance(encoded, str) and len(encoded) <= MAX_IMAGE_BYTES * 4 // 3 + 4:
        try:
            raw = base64.b64decode(encoded, validate=True)
            if len(raw) <= MAX_IMAGE_BYTES:
                with Image.open(io.BytesIO(raw)) as image:
                    if image.width * image.height <= MAX_IMAGE_PIXELS:
                        digest = image_digest(image)
        except Exception:  # noqa: BLE001 - any decode failure is the same fixed refusal
            digest = None
    if digest is None:
        # Raised outside the except block: a library message could quote the input.
        raise RecordingError(IMAGE_REFUSED)
    return digest


def _digest_list(body: Mapping[str, Any]) -> list[str] | None:
    """The image digests of a body: from `images` (live) or `image_digests` (stored), or None."""
    if IMAGES_FIELD in body and DIGESTS_FIELD in body:
        raise RecordingError("the request body holds both images and image_digests")
    if IMAGES_FIELD in body:
        images = body[IMAGES_FIELD]
        if not isinstance(images, list) or not 1 <= len(images) <= MAX_IMAGES:
            raise RecordingError(f"the request images are not a list of 1 to {MAX_IMAGES} images")
        return [_image_digest(image) for image in images]
    if DIGESTS_FIELD in body:
        digests = body[DIGESTS_FIELD]
        if (
            not isinstance(digests, list)
            or not 1 <= len(digests) <= MAX_IMAGES
            or not all(isinstance(d, str) and KEY_RE.fullmatch(d) for d in digests)
        ):
            raise RecordingError(
                f"the request image_digests are not a list of 1 to {MAX_IMAGES} sha256 digests"
            )
        return list(digests)
    return None


def canonical_request(body: object) -> dict[str, Any]:
    """The fields of an `/api/generate` body that the key covers (TST-005.D5, TST-009.D2)."""
    if not isinstance(body, Mapping):
        raise RecordingError("the request body is not a JSON object")
    missing = [field for field in KEYED_FIELDS if field not in body]
    if missing:
        raise RecordingError(f"the request body lacks {', '.join(missing)}")
    canonical = {field: body[field] for field in KEYED_FIELDS}
    canonical.update({field: body[field] for field in OPTIONAL_KEYED_FIELDS if field in body})
    digests = _digest_list(body)
    if digests is not None:
        from tests.recordings.vision import check_text_input

        # TST-009.D2: the prompt of an image request is held to TST-008.D9's text rule.
        if not isinstance(body["prompt"], str):
            raise RecordingError("the prompt of an image request is not text")
        check_text_input(body["prompt"])
        canonical[DIGESTS_FIELD] = digests
    return canonical


def stored_request(body: Mapping[str, Any]) -> dict[str, Any]:
    """`body` as a recording stores it: `images` replaced by their digests (TST-009.D2)."""
    digests = _digest_list(body)
    if digests is None:
        return dict(body)
    stored = {k: v for k, v in body.items() if k != IMAGES_FIELD}
    stored[DIGESTS_FIELD] = digests
    return stored


def recording_key(body: object) -> str:
    """The SHA-256 hex digest of the canonical request: a recording's file name, without .json."""
    text = json.dumps(
        canonical_request(body), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    try:
        data = text.encode("utf-8")
    except UnicodeEncodeError:
        # A lone surrogate: the error would quote the text, so it is not chained.
        raise RecordingError("the request body is not valid UTF-8 text") from None
    return hashlib.sha256(data).hexdigest()


def package_dir(package: str, root: Path = RECORDINGS) -> Path:
    """`root/<package>`; the name is one plain segment, so it can't leave `root`."""
    if not PACKAGE_RE.fullmatch(package):
        # Fixed text: the name is never echoed (PR #71 privacy audit).
        raise RecordingError("a recording package name is not a plain lower-case name")
    return root / package


def describe(path: Path, root: Path | None = None) -> str:
    """A label for `path` that is safe in test output (PR #71 privacy audit).

    Only a valid `<package>/<64-hex key>.json` is shown as it is. Any other file or folder
    name could describe an original, so it is reported by a short SHA-256 of its path
    (relative to `root` when given) instead.
    """
    in_place = root is None or path.parent.parent == root
    if (
        in_place
        and PACKAGE_RE.fullmatch(path.parent.name)
        and path.suffix == ".json"
        and KEY_RE.fullmatch(path.stem)
    ):
        return f"recording {path.parent.name}/{path.name}"
    name = path.relative_to(root).as_posix() if root is not None else path.name
    digest = hashlib.sha256(name.encode("utf-8", "surrogatepass")).hexdigest()[:12]
    return f"a file not named <package>/<key>.json (path sha256 {digest})"


def _is_file(path: Path, where: str) -> bool:
    """`path.is_file()`, with an `OSError` (its text carries the path) turned into a labelled,
    unchained `RecordingError` (PR #71). Every filesystem call in this module is wrapped so.
    """
    try:
        return path.is_file()
    except OSError:
        raise RecordingError(f"{where} cannot be read as a file") from None


def _is_symlink(path: Path, where: str) -> bool:
    try:
        return path.is_symlink()
    except OSError:
        raise RecordingError(f"{where} cannot be read as a file") from None


def _is_vision_file(path: Path) -> bool:
    """True when the stored request has a `kind`: a TST-008 vision recording, not an Ollama one.

    Any read or parse failure is False here; the loader that follows reports it by label.
    """
    try:
        recording = json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return False
    return isinstance(recording, dict) and (
        isinstance(recording.get("request"), Mapping) and "kind" in recording["request"]
    )


def load_recording(path: Path, root: Path | None = None) -> dict[str, Any]:
    """A recording file, checked against the format; its name must be its request's key.

    Pass the lint's `root` so a stray file gets the same label in every message.
    """
    where = describe(path, root)
    try:
        data = path.read_bytes()
    except OSError:
        # The OSError's text carries the full path, so it is not chained (PR #71).
        raise RecordingError(f"{where} cannot be read as a file") from None
    try:
        recording = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RecordingError(f"{where} is not UTF-8 JSON") from None
    if not isinstance(recording, dict) or set(recording) != RECORDING_FIELDS:
        raise RecordingError(f"{where} must hold exactly the keys request and response")
    response = recording["response"]
    if not isinstance(response, dict) or not isinstance(response.get("response"), str):
        raise RecordingError(f"{where} has no text response.response field")
    request = recording["request"]
    if isinstance(request, Mapping):
        if IMAGES_FIELD in request:
            raise RecordingError(f"{where} carries images; store image_digests instead")
        if DIGESTS_FIELD in request and not set(request) <= IMAGE_REQUEST_FIELDS:
            raise RecordingError(f"{where} holds a field an image request may not have")
    try:
        key = recording_key(request)
    except RecordingError:
        key = None
    if key is None:
        raise RecordingError(f"{where} holds a request that cannot be keyed")
    if key != path.stem:
        raise RecordingError(f"{where} is not named by the key of its stored request")
    return recording


def lint_recordings(root: Path = RECORDINGS) -> list[str]:
    """Every problem with the `*.json` files under `root`, one line each (TST-005.1.3).

    Each file sits in `<package>/`, follows the format, is named by its request's key, and
    its request holds no `images` field, only `image_digests` (TST-009.D2). A request with a
    `kind` is a vision recording (TST-008.D3) and is checked by `tests.recordings.vision` instead.
    """
    try:
        paths = sorted(root.rglob("*.json"))
    except OSError:
        # Fixed text: the failing subtree's path is not echoed (PR #71).
        return ["the recordings tree cannot be walked; no recording was checked"]
    problems = []
    for path in paths:
        where = describe(path, root)
        parts = path.relative_to(root).parts
        try:
            if not _is_file(path, where):  # a folder named *.json, a broken link, a device
                raise RecordingError(f"{where} is not a regular file")
            if len(parts) != 2:
                raise RecordingError(f"{where} must sit directly in tests/recordings/<package>/")
            if not PACKAGE_RE.fullmatch(parts[0]):
                raise RecordingError(f"{where} is not in a plain lower-case package folder")
            if _is_symlink(path, where):
                raise RecordingError(f"{where} is a link; recordings are plain files")
            if _is_vision_file(path):
                # TST-008.1: the vision format is checked by its own loader (TST-008.D3, D7).
                from tests.recordings.vision import load_vision_recording

                load_vision_recording(path, where)
            else:
                load_recording(path, root)
        except RecordingError as exc:
            problems.append(str(exc))
    return problems


def _request_body(request: httpx.Request) -> dict[str, Any]:
    if request.method != "POST" or request.url.path != GENERATE_PATH:
        raise RecordingError(f"only POST {GENERATE_PATH} is recorded")
    try:
        body = json.loads(request.read().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RecordingError("the request body is not UTF-8 JSON") from None
    if not isinstance(body, dict):
        raise RecordingError("the request body is not a JSON object")
    return body


def _check_host(request: httpx.Request) -> None:
    """Record mode forwards only to OllamaClient's allowed hosts, whatever client it is in."""
    bare = request.url.copy_with(path="/", query=None, fragment=None)
    try:
        check_host(str(bare))
    except OllamaError:
        # Fixed text: the refused host is not echoed (PR #71).
        raise RecordingError(
            "record mode forwards only to the hosts in classifier.models.ollama.ALLOWED_HOSTS"
        ) from None


class ReplayTransport(httpx.BaseTransport):
    """Serves recorded `/api/generate` responses. A miss raises `RecordingError`.

    Every failure is also kept in `failures`, so the fixture can fail the test at teardown
    even if the code under test swallowed the exception.
    """

    def __init__(self, package: str, test_id: str, root: Path = RECORDINGS) -> None:
        self.directory = package_dir(package, root)
        self.test_id = test_id
        self.failures: list[str] = []

    def _fail(self, problem: str) -> RecordingError:
        message = f"{problem} (test {self.test_id})"
        self.failures.append(message)
        return RecordingError(message)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            key = recording_key(_request_body(request))
            path = self.directory / f"{key}.json"
            if not _is_file(path, describe(path)):
                raise RecordingError(
                    f"no recording {self.directory.name}/{key}.json; {RECORD_HINT}"
                )
            recording = load_recording(path)
        except RecordingError as exc:
            raise self._fail(str(exc)) from None
        return httpx.Response(200, json=recording["response"])


class RecordingTransport(httpx.BaseTransport):
    """Record mode: forwards to `upstream` and writes each successful answer as a recording.

    An existing recording with the same answer is left as it is (timings differ between runs).
    A different answer fails, naming the key: overwriting it silently would hide a model change.
    Delete the file first to re-record on purpose.
    """

    def __init__(
        self, package: str, upstream: httpx.BaseTransport, test_id: str, root: Path = RECORDINGS
    ) -> None:
        self.directory = package_dir(package, root)
        self.upstream = upstream
        self.test_id = test_id
        self.failures: list[str] = []

    def _fail(self, problem: str) -> RecordingError:
        message = f"{problem} (test {self.test_id})"
        self.failures.append(message)
        return RecordingError(message)

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        try:
            _check_host(request)
            body = _request_body(request)
            key = recording_key(body)
        except RecordingError as exc:
            raise self._fail(str(exc)) from None
        upstream = self.upstream.handle_request(request)
        try:
            content = upstream.read()
        finally:
            upstream.close()
        if upstream.status_code != 200:
            return httpx.Response(upstream.status_code, content=content)
        name = f"{self.directory.name}/{key}.json"
        try:
            payload = json.loads(content.decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            raise self._fail(f"Ollama's reply for {name} is not UTF-8 JSON") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
            raise self._fail(f"Ollama's reply for {name} has no text response field")
        recorded = {k: v for k, v in payload.items() if k not in UNRECORDED_RESPONSE_FIELDS}
        path = self.directory / f"{key}.json"
        try:
            existing = load_recording(path) if _is_file(path, f"recording {name}") else None
        except RecordingError as exc:
            raise self._fail(f"{exc}; delete it to re-record") from None
        if existing is not None:
            if existing["response"]["response"] != recorded["response"]:
                raise self._fail(
                    f"recording {name} exists with a different answer; delete it to re-record"
                )
            return httpx.Response(200, json=payload)
        text = json.dumps(
            {"request": stored_request(body), "response": recorded},
            sort_keys=True,
            indent=2,
            ensure_ascii=False,
        )
        # Encoded before the file is opened, so a bad reply leaves no partial recording.
        try:
            data = (text + "\n").encode("utf-8")
        except UnicodeEncodeError:
            # A lone surrogate in the reply: the error would quote it, so it is not chained.
            raise self._fail(f"Ollama's reply for {name} is not valid UTF-8 text") from None
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        except OSError:
            # The OSError's text carries the checkout path, so it is not chained (PR #71).
            raise self._fail(f"recording {name} cannot be written") from None
        return httpx.Response(200, json=payload)
