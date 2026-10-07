"""TST-005.1: replay recorded Ollama responses outside the `gpu` tier (CLAUDE.md §3).

Format (TST-005.D3, D5): one JSON file per request, `tests/recordings/<package>/<key>.json`,
holding `{"request": <the /api/generate body as sent>, "response": <Ollama's JSON reply>}`.
The key is the SHA-256 of the canonical request: `json.dumps` of `model`, `prompt`, `format`
and `options`, plus `think` and `raw` only when the body carries them, with `sort_keys=True`,
`separators=(",", ":")`, `ensure_ascii=False`, encoded as UTF-8. `keep_alive` and `stream`
are not part of the key.

`ReplayTransport` serves those files to `OllamaClient(host, transport=...)` and never opens a
socket. `RecordingTransport` (record mode, `gpu` tier only) forwards to an upstream transport
that the caller builds, and writes the files. The shared `ollama_transport` fixture in
tests/conftest.py picks between them.

Privacy (SAN-001.D10, DOC-007.D1): recordings come from synthetic strings only. Every error
names at most the package, the 64-hex key and the test id, never a prompt, schema or answer,
and is raised unchained.
"""

import hashlib
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


def canonical_request(body: object) -> dict[str, Any]:
    """The fields of an `/api/generate` body that the key covers (TST-005.D5)."""
    if not isinstance(body, Mapping):
        raise RecordingError("the request body is not a JSON object")
    missing = [field for field in KEYED_FIELDS if field not in body]
    if missing:
        raise RecordingError(f"the request body lacks {', '.join(missing)}")
    canonical = {field: body[field] for field in KEYED_FIELDS}
    canonical.update({field: body[field] for field in OPTIONAL_KEYED_FIELDS if field in body})
    return canonical


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


def load_recording(path: Path, root: Path | None = None) -> dict[str, Any]:
    """A recording file, checked against the format; its name must be its request's key.

    Pass the lint's `root` so a stray file gets the same label in every message.
    """
    where = describe(path, root)
    try:
        recording = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise RecordingError(f"{where} is not UTF-8 JSON") from None
    if not isinstance(recording, dict) or set(recording) != RECORDING_FIELDS:
        raise RecordingError(f"{where} must hold exactly the keys request and response")
    response = recording["response"]
    if not isinstance(response, dict) or not isinstance(response.get("response"), str):
        raise RecordingError(f"{where} has no text response.response field")
    if recording_key(recording["request"]) != path.stem:
        raise RecordingError(f"{where} is not named by the key of its stored request")
    return recording


def lint_recordings(root: Path = RECORDINGS) -> list[str]:
    """Every problem with the `*.json` files under `root`, one line each (TST-005.1.3).

    Each file sits in `<package>/`, follows the format, is named by its request's key, and
    its request is text only (P-3: never an `images` field).
    """
    problems = []
    for path in sorted(root.rglob("*.json")):
        where = describe(path, root)
        parts = path.relative_to(root).parts
        try:
            if len(parts) != 2:
                raise RecordingError(f"{where} must sit directly in tests/recordings/<package>/")
            if not PACKAGE_RE.fullmatch(parts[0]):
                raise RecordingError(f"{where} is not in a plain lower-case package folder")
            if "images" in load_recording(path, root)["request"]:
                raise RecordingError(f"{where} carries images; recordings are text only")
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
            if not path.is_file():
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
        if path.is_file():
            try:
                existing = load_recording(path)
            except RecordingError as exc:
                raise self._fail(f"{exc}; delete it to re-record") from None
            if existing["response"]["response"] != recorded["response"]:
                raise self._fail(
                    f"recording {name} exists with a different answer; delete it to re-record"
                )
        else:
            text = json.dumps(
                {"request": body, "response": recorded},
                sort_keys=True,
                indent=2,
                ensure_ascii=False,
            )
            self.directory.mkdir(parents=True, exist_ok=True)
            path.write_text(text + "\n", encoding="utf-8", newline="\n")
        return httpx.Response(200, json=payload)
