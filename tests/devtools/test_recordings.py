"""TST-005.1: the Ollama replay format, transports and fixture (CLAUDE.md §3, TST-005.D3, D5).

Unit tier: every recording here is synthetic and lives under `tmp_path`, every "upstream" is an
`httpx.MockTransport`, and nothing reaches Ollama. The planted SECRET stands in for a prompt or
answer that must never appear in an error.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from classifier.models.ollama import OllamaClient, OllamaError
from tests.recordings.replay import (
    RecordingError,
    RecordingTransport,
    ReplayTransport,
    canonical_request,
    lint_recordings,
    load_recording,
    package_dir,
    recording_key,
)

HOST = "http://localhost"
TEST_ID = "tests/unit/pkg/test_x.py::test_y"
SECRET = "zz-planted-secret-qx"
SCHEMA = {"type": "object", "properties": {"word": {"type": "string"}}, "required": ["word"]}
OPTIONS = {"temperature": 0, "seed": 7}


def body(**extra: Any) -> dict[str, Any]:
    return {
        "model": "synthetic-model:1b",
        "prompt": f"Say a word. {SECRET}",
        "format": SCHEMA,
        "options": OPTIONS,
        "keep_alive": 0,
        "stream": False,
        **extra,
    }


def answer(word: str = SECRET) -> dict[str, Any]:
    return {"model": "synthetic-model:1b", "response": json.dumps({"word": word}), "done": True}


def write_recording(root: Path, request: dict[str, Any], response: dict[str, Any]) -> Path:
    path = root / "pkg" / f"{recording_key(request)}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"request": request, "response": response}), encoding="utf-8")
    return path


def generate(transport: httpx.BaseTransport, **extra: Any) -> dict[str, Any]:
    with OllamaClient(HOST, transport=transport) as client:
        return client.generate_json(
            model="synthetic-model:1b",
            prompt=f"Say a word. {SECRET}",
            schema=SCHEMA,
            options=OPTIONS,
            keep_alive=0,
            **extra,
        )


def assert_private(exc: BaseException) -> None:
    """No prompt or answer text, and no chained exception that could carry one."""
    assert SECRET not in str(exc) and SECRET not in repr(exc)
    assert exc.__cause__ is None
    assert exc.__suppress_context__ or exc.__context__ is None


# --- the key (TST-005.D5) ---


def test_key_is_the_sha256_of_the_canonical_json() -> None:
    canonical = {"model": "m", "prompt": "p", "format": SCHEMA, "options": OPTIONS}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    expected = hashlib.sha256(text.encode("utf-8")).hexdigest()
    assert recording_key({**canonical, "keep_alive": "5m", "stream": False}) == expected


def test_key_is_pinned() -> None:
    # Hand-computed once; a change here means every committed recording must be re-keyed.
    request = {"model": "m", "prompt": "p", "format": "json", "options": {}}
    text = '{"format":"json","model":"m","options":{},"prompt":"p"}'
    assert recording_key(request) == hashlib.sha256(text.encode()).hexdigest()


def test_keep_alive_and_stream_do_not_change_the_key() -> None:
    assert recording_key(body()) == recording_key(body(keep_alive="30m", stream=True))
    without = {k: v for k, v in body().items() if k not in {"keep_alive", "stream"}}
    assert recording_key(without) == recording_key(body())


@pytest.mark.parametrize("field", ["think", "raw"])
def test_think_and_raw_are_keyed_only_when_present(field: str) -> None:
    keys = {recording_key(body()), recording_key(body(**{field: False}))}
    keys.add(recording_key(body(**{field: True})))
    assert len(keys) == 3
    assert field not in canonical_request(body())
    assert canonical_request(body(**{field: False}))[field] is False


@pytest.mark.parametrize("field", ["model", "prompt", "format", "options"])
def test_every_keyed_field_changes_the_key(field: str) -> None:
    assert recording_key(body()) != recording_key(body(**{field: "other"}))


def test_unknown_fields_are_not_keyed() -> None:
    assert recording_key(body()) == recording_key(body(images_never_sent=1))


def test_non_ascii_is_hashed_as_utf8_not_escaped() -> None:
    request = body(prompt="café – 東京")
    text = json.dumps(
        canonical_request(request), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert "café – 東京" in text
    assert recording_key(request) == hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_lone_surrogate_fails_without_echoing_the_text() -> None:
    with pytest.raises(RecordingError) as caught:
        recording_key(body(prompt=f"{SECRET}\ud800"))
    assert_private(caught.value)


@pytest.mark.parametrize("bad", [None, [], "text", {"model": "m", "prompt": "p"}])
def test_a_body_without_the_keyed_fields_is_refused(bad: object) -> None:
    with pytest.raises(RecordingError):
        recording_key(bad)


@pytest.mark.parametrize("name", ["", "../x", "Models", "a/b", "a.b", "1x"])
def test_package_names_are_plain_segments(name: str, tmp_path: Path) -> None:
    with pytest.raises(RecordingError):
        package_dir(name, tmp_path)


# --- replay ---


def test_replay_round_trips_through_ollama_client(tmp_path: Path) -> None:
    write_recording(tmp_path, body(), answer("alpha"))
    transport = ReplayTransport("pkg", TEST_ID, root=tmp_path)
    assert generate(transport) == {"word": "alpha"}
    assert transport.failures == []


def test_replay_matches_think_and_raw_as_sent(tmp_path: Path) -> None:
    write_recording(tmp_path, body(think=False), answer("alpha"))
    assert generate(ReplayTransport("pkg", TEST_ID, root=tmp_path), think=False) == {
        "word": "alpha"
    }
    with pytest.raises(RecordingError):
        generate(ReplayTransport("pkg", TEST_ID, root=tmp_path))


def test_a_missing_recording_names_the_key_and_the_test(tmp_path: Path) -> None:
    transport = ReplayTransport("pkg", TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError) as caught:
        generate(transport)
    message = str(caught.value)
    assert f"pkg/{recording_key(body())}.json" in message
    assert TEST_ID in message and "--record-ollama" in message
    assert_private(caught.value)
    assert transport.failures == [message]


def test_a_missing_recording_is_not_an_ollama_error_and_escapes_except_exception(
    tmp_path: Path,
) -> None:
    transport = ReplayTransport("pkg", TEST_ID, root=tmp_path)
    escaped = False
    try:
        try:
            generate(transport)
        except Exception:  # a fail-closed caller, like the sanitizer (SAN-001.D2)
            pytest.fail("RecordingError was caught by except Exception")
    except RecordingError:
        escaped = True
    assert escaped
    assert not issubclass(RecordingError, (Exception, OllamaError))


@pytest.mark.parametrize(
    ("method", "path"), [("GET", "/api/generate"), ("POST", "/api/chat"), ("GET", "/api/tags")]
)
def test_only_post_generate_is_served(method: str, path: str, tmp_path: Path) -> None:
    transport = ReplayTransport("pkg", TEST_ID, root=tmp_path)
    with httpx.Client(base_url=HOST, transport=transport) as client:
        with pytest.raises(RecordingError):
            client.request(method, path, json=body())
    assert len(transport.failures) == 1


def test_a_misnamed_recording_fails(tmp_path: Path) -> None:
    good = write_recording(tmp_path, body(prompt="other"), answer())
    good.rename(good.with_name(f"{recording_key(body())}.json"))
    with pytest.raises(RecordingError, match="not named by the key") as caught:
        generate(ReplayTransport("pkg", TEST_ID, root=tmp_path))
    assert_private(caught.value)


def test_a_tampered_request_fails(tmp_path: Path) -> None:
    path = write_recording(tmp_path, body(), answer())
    recording = json.loads(path.read_text(encoding="utf-8"))
    recording["request"]["options"] = {"temperature": 1}
    path.write_text(json.dumps(recording), encoding="utf-8")
    with pytest.raises(RecordingError, match="not named by the key"):
        generate(ReplayTransport("pkg", TEST_ID, root=tmp_path))


@pytest.mark.parametrize(
    "content",
    [
        b"{not json",
        b"\xff\xfe",
        b"[]",
        json.dumps({"request": body()}).encode(),
        json.dumps({"request": body(), "response": answer(), "extra": 1}).encode(),
        json.dumps({"request": body(), "response": {"done": True}}).encode(),
        json.dumps({"request": body(), "response": {"response": 3}}).encode(),
    ],
)
def test_a_malformed_recording_fails_privately(content: bytes, tmp_path: Path) -> None:
    path = package_dir("pkg", tmp_path) / f"{recording_key(body())}.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    with pytest.raises(RecordingError) as caught:
        generate(ReplayTransport("pkg", TEST_ID, root=tmp_path))
    assert_private(caught.value)


def test_load_recording_returns_both_halves(tmp_path: Path) -> None:
    path = write_recording(tmp_path, body(), answer("alpha"))
    recording = load_recording(path)
    assert recording["request"] == body() and recording["response"] == answer("alpha")


# --- record mode ---


def upstream(reply: dict[str, Any], status: int = 200) -> httpx.MockTransport:
    return httpx.MockTransport(lambda request: httpx.Response(status, json=reply))


def test_record_writes_the_format_and_replay_serves_it(tmp_path: Path) -> None:
    reply = {**answer("alpha"), "context": [1, 2, 3], "total_duration": 5}
    recorder = RecordingTransport("pkg", upstream(reply), TEST_ID, root=tmp_path)
    assert generate(recorder, think=True) == {"word": "alpha"}

    path = tmp_path / "pkg" / f"{recording_key(body(think=True))}.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert stored["request"] == body(think=True)
    assert stored["response"] == {**answer("alpha"), "total_duration": 5}  # no `context`
    assert path.read_bytes().endswith(b"}\n") and b"\r\n" not in path.read_bytes()

    assert generate(ReplayTransport("pkg", TEST_ID, root=tmp_path), think=True) == {"word": "alpha"}


def test_record_writes_non_ascii_as_utf8(tmp_path: Path) -> None:
    reply = {**answer(), "response": json.dumps({"word": "東京"}, ensure_ascii=False)}
    recorder = RecordingTransport("pkg", upstream(reply), TEST_ID, root=tmp_path)
    assert generate(recorder) == {"word": "東京"}
    (path,) = (tmp_path / "pkg").iterdir()
    assert "東京" in path.read_text(encoding="utf-8")


def test_record_keeps_an_existing_recording_with_the_same_answer(tmp_path: Path) -> None:
    path = write_recording(tmp_path, body(), {**answer("alpha"), "total_duration": 1})
    before = path.read_bytes()
    reply = {**answer("alpha"), "total_duration": 2}
    generate(RecordingTransport("pkg", upstream(reply), TEST_ID, root=tmp_path))
    assert path.read_bytes() == before


def test_record_refuses_to_overwrite_a_different_answer(tmp_path: Path) -> None:
    path = write_recording(tmp_path, body(), answer("alpha"))
    before = path.read_bytes()
    recorder = RecordingTransport("pkg", upstream(answer("beta")), TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError, match="different answer") as caught:
        generate(recorder)
    assert recording_key(body()) in str(caught.value) and TEST_ID in str(caught.value)
    assert_private(caught.value)
    assert path.read_bytes() == before
    assert len(recorder.failures) == 1


def test_record_does_not_write_an_http_error(tmp_path: Path) -> None:
    recorder = RecordingTransport("pkg", upstream({"error": "x"}, 404), TEST_ID, root=tmp_path)
    with pytest.raises(OllamaError, match="HTTP 404"):
        generate(recorder)
    assert not (tmp_path / "pkg").exists()


def test_record_refuses_a_reply_without_a_text_response(tmp_path: Path) -> None:
    recorder = RecordingTransport("pkg", upstream({"done": True}), TEST_ID, root=tmp_path)
    with pytest.raises(RecordingError) as caught:
        generate(recorder)
    assert_private(caught.value)
    assert not (tmp_path / "pkg").exists()


# --- the shared fixture (tests/conftest.py), run in a synthetic tree with pytester ---

pytest_plugins = ["pytester"]

REPO_TESTS = Path(__file__).resolve().parents[1]
INNER_SECRET = "zz-inner-" + "secret-qx"  # never written whole into the inner sources
INNER_UNIT = """
import pytest
from classifier.models.ollama import OllamaClient
from tests.recordings.replay import ReplayTransport

PROMPT = "zz-inner-" + "secret-qx"


def call(transport):
    with OllamaClient("http://localhost", transport=transport) as client:
        client.generate_json(model="m", prompt=PROMPT, schema={}, options={}, keep_alive=0)


def test_replays(ollama_transport):
    assert isinstance(ollama_transport("models"), ReplayTransport)


def test_miss(ollama_transport):
    call(ollama_transport("models"))


def test_swallowed(ollama_transport):
    try:
        call(ollama_transport("models"))
    except BaseException:
        pass
"""
INNER_GPU = """
import httpx
from tests.recordings.replay import RecordingTransport


def test_transport(ollama_transport, pytestconfig):
    transport = ollama_transport("models")
    if pytestconfig.getoption("--record-ollama"):
        assert isinstance(transport, RecordingTransport)
    else:
        assert type(transport) is httpx.HTTPTransport
"""


@pytest.fixture
def inner(pytester: pytest.Pytester) -> pytest.Pytester:
    """A copy of the real conftest and replay helper, with one unit and one gpu module."""
    tests = pytester.path / "tests"
    (tests / "recordings").mkdir(parents=True)
    (tests / "unit").mkdir()
    (tests / "gpu").mkdir()
    for rel in ("conftest.py", "recordings/replay.py"):
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
    key = recording_key(
        {"model": "m", "prompt": INNER_SECRET, "format": {}, "options": {}, "keep_alive": 0}
    )
    assert f"no recording models/{key}.json" in output
    assert "tests/unit/test_inner_unit.py::test_miss" in output
    # The swallowed miss fails at teardown, naming its own test.
    assert "caught by the code under test" in output
    assert "tests/unit/test_inner_unit.py::test_swallowed" in output
    assert INNER_SECRET not in output


def test_fixture_is_the_real_transport_in_gpu(inner: pytest.Pytester) -> None:
    run_inner(inner, "-m", "gpu").assert_outcomes(passed=1)


def test_fixture_records_in_gpu_with_the_option(inner: pytest.Pytester) -> None:
    run_inner(inner, "-m", "gpu", "--record-ollama").assert_outcomes(passed=1)


def test_record_option_is_refused_when_other_tiers_are_selected(inner: pytest.Pytester) -> None:
    result = run_inner(inner, "--record-ollama")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    result.stderr.fnmatch_lines(["*--record-ollama is for the gpu tier only*"])


# --- the committed recordings (TST-005.1.3) ---


def test_every_committed_recording_follows_the_format() -> None:
    # The real tree: every workers' recording under tests/recordings/ (TST-005.D1).
    assert lint_recordings() == []


def test_lint_accepts_a_good_recording_in_any_whitespace(tmp_path: Path) -> None:
    path = write_recording(tmp_path, body(think=False), answer())
    path.write_text(json.dumps(json.loads(path.read_text("utf-8")), indent=4), encoding="utf-8")
    assert lint_recordings(tmp_path) == []


def test_lint_reports_each_bad_file_privately(tmp_path: Path) -> None:
    good = write_recording(tmp_path, body(), answer())
    (tmp_path / "loose.json").write_text("{}", encoding="utf-8")
    nested = tmp_path / "pkg" / "deeper"
    nested.mkdir()
    (nested / good.name).write_bytes(good.read_bytes())
    misnamed = write_recording(tmp_path, body(prompt="other"), answer())
    misnamed.rename(misnamed.with_name("0" * 64 + ".json"))
    write_recording(tmp_path, body(prompt="with images", images=["aGVsbG8="]), answer())
    (tmp_path / "Bad").mkdir()
    (tmp_path / "Bad" / good.name).write_bytes(good.read_bytes())

    problems = lint_recordings(tmp_path)
    assert len(problems) == 5
    assert any("loose.json" in p for p in problems)
    assert any("pkg/deeper/" in p for p in problems)
    assert any("not named by the key" in p for p in problems)
    assert any("carries images" in p for p in problems)
    assert any("'Bad'" in p for p in problems)
    assert all(SECRET not in p for p in problems)
