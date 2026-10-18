"""MOD-001.1: the Ollama text client, through `httpx.MockTransport` only (never live Ollama).

Hosts in this module carry no port on purpose: the tier audit flags the Ollama port in a unit
test (TST-002.2).
"""

import hashlib
import json
from collections.abc import Callable

import httpx
import pytest

from classifier.models.ollama import (
    DEFAULT_TIMEOUT,
    GENERATE_PATH,
    HOST_ENV,
    OllamaClient,
    OllamaError,
    OllamaUnavailable,
)

HOST = "http://ollama"
PROMPT = "Find the entities in: synthetic sample text"
SCHEMA = {"type": "object", "properties": {"entities": {"type": "array"}}}
OPTIONS = {"temperature": 0, "seed": 7}
ANSWER = {"entities": [{"text": "synthetic", "label": "org"}]}

Handler = Callable[[httpx.Request], httpx.Response]


def ok(answer: object = ANSWER) -> Handler:
    return lambda request: httpx.Response(200, json={"response": json.dumps(answer)})


def client(handler: Handler, host: str = HOST) -> OllamaClient:
    return OllamaClient(host, transport=httpx.MockTransport(handler))


def generate(c: OllamaClient, **overrides: object) -> dict:
    args: dict = {
        "model": "tag:1b",
        "prompt": PROMPT,
        "schema": SCHEMA,
        "options": OPTIONS,
        "keep_alive": "5m",
    }
    return c.generate_json(**(args | overrides))


def capture() -> tuple[list[httpx.Request], Handler]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return ok()(request)

    return seen, handler


def test_request_shape() -> None:
    seen, handler = capture()
    generate(client(handler))
    (request,) = seen
    assert request.method == "POST"
    assert request.url == httpx.URL(HOST + GENERATE_PATH)
    assert json.loads(request.content) == {
        "model": "tag:1b",
        "prompt": PROMPT,
        "format": SCHEMA,
        "options": OPTIONS,
        "keep_alive": "5m",
        "stream": False,
    }


def test_request_is_text_only_by_default() -> None:
    seen, handler = capture()
    generate(client(handler))
    body = json.loads(seen[0].content)
    assert "images" not in body and "system" not in body


def test_images_and_system_are_sent_when_given() -> None:
    seen, handler = capture()
    generate(client(handler), images=["aGk="], system="synthetic system text")
    body = json.loads(seen[0].content)
    assert body["images"] == ["aGk="]
    assert body["system"] == "synthetic system text"


def test_empty_images_are_not_sent() -> None:
    seen, handler = capture()
    generate(client(handler), images=[])
    assert "images" not in json.loads(seen[0].content)


@pytest.mark.parametrize("exc_type", [httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout])
def test_unreachable_or_timeout_is_unavailable(exc_type: type[httpx.TransportError]) -> None:
    with pytest.raises(OllamaUnavailable):
        generate(client(raising(exc_type)))


def test_unavailable_is_still_an_ollama_error() -> None:
    assert issubclass(OllamaUnavailable, OllamaError)


def test_a_bad_status_or_body_is_not_unavailable() -> None:
    with pytest.raises(OllamaError) as status:
        generate(client(lambda request: httpx.Response(500)))
    with pytest.raises(OllamaError) as body:
        generate(client(lambda request: httpx.Response(200, json={"response": "not json"})))
    assert not isinstance(status.value, OllamaUnavailable)
    assert not isinstance(body.value, OllamaUnavailable)


@pytest.mark.parametrize("think", [False, True])
def test_think_is_sent_only_when_set(think: bool) -> None:
    seen, handler = capture()
    generate(client(handler), think=think)
    assert json.loads(seen[0].content)["think"] is think


def test_raw_is_absent_by_default() -> None:
    seen, handler = capture()
    generate(client(handler))
    generate(client(handler), raw=False)
    assert all("raw" not in json.loads(r.content) for r in seen)


def test_raw_is_sent_when_set() -> None:
    seen, handler = capture()
    generate(client(handler), raw=True)
    assert json.loads(seen[0].content)["raw"] is True


def test_options_and_keep_alive_pass_through_unchanged() -> None:
    seen, handler = capture()
    options = {"temperature": 0.2, "seed": 42, "num_ctx": 4096, "top_p": 0.9}
    generate(client(handler), options=options, keep_alive=0, model="other:2b")
    body = json.loads(seen[0].content)
    assert body["options"] == options
    assert body["keep_alive"] == 0
    assert body["model"] == "other:2b"


def test_returns_the_parsed_answer() -> None:
    assert generate(client(ok())) == ANSWER


def test_default_timeout_is_applied() -> None:
    seen, handler = capture()
    generate(client(handler))
    assert seen[0].extensions["timeout"]["read"] == DEFAULT_TIMEOUT


def test_custom_timeout_is_applied() -> None:
    seen, handler = capture()
    c = OllamaClient(HOST, transport=httpx.MockTransport(handler), timeout=12.5)
    generate(c)
    assert seen[0].extensions["timeout"]["read"] == 12.5


def raising(exc_type: type[httpx.TransportError]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_type("synthetic failure", request=request)

    return handler


@pytest.mark.parametrize(
    ("handler", "message"),
    [
        (raising(httpx.ConnectError), "cannot reach Ollama"),
        (raising(httpx.ReadTimeout), "timed out"),
        (lambda r: httpx.Response(404, json={"error": "model not found"}), "HTTP 404"),
        (lambda r: httpx.Response(500, text="boom"), "HTTP 500"),
        (lambda r: httpx.Response(200, text="not json"), "not JSON"),
        (lambda r: httpx.Response(200, json={"done": True}), "no text `response`"),
        (lambda r: httpx.Response(200, json=["list"]), "no text `response`"),
        (lambda r: httpx.Response(200, json={"response": "{broken"}), "not valid JSON"),
        (lambda r: httpx.Response(200, json={"response": "[1, 2]"}), "not a JSON object"),
        # MOD-001.D5: a runaway answer cut at num_predict fails closed, empty or not.
        (
            lambda r: httpx.Response(200, json={"response": "", "done_reason": "length"}),
            "cut off at the token limit",
        ),
        (
            lambda r: httpx.Response(200, json={"response": "{}", "done_reason": "length"}),
            "cut off at the token limit",
        ),
        (lambda r: httpx.Response(200, json={"response": ""}), "not valid JSON"),
    ],
)
def test_each_failure_is_one_ollama_error(handler: Handler, message: str) -> None:
    with pytest.raises(OllamaError, match=message) as info:
        generate(client(handler))
    assert PROMPT not in str(info.value)
    assert "synthetic sample text" not in str(info.value)


def test_error_names_the_prompt_hash_not_the_prompt() -> None:
    with pytest.raises(OllamaError) as info:
        generate(client(lambda r: httpx.Response(500)))
    assert hashlib.sha256(PROMPT.encode()).hexdigest()[:8] in str(info.value)


def test_error_does_not_echo_the_answer() -> None:
    secret = "synthetic-answer-text"
    with pytest.raises(OllamaError) as info:
        generate(client(lambda r: httpx.Response(200, json={"response": f"[{secret!r}"})))
    assert secret not in str(info.value)
    assert info.value.__cause__ is None


@pytest.mark.parametrize(
    "host",
    ["http://ollama", "http://localhost", "http://127.0.0.1", "http://[::1]", "https://ollama/"],
)
def test_allowed_hosts(host: str) -> None:
    assert generate(client(ok(), host=host)) == ANSWER


@pytest.mark.parametrize(
    "host",
    [
        "http://example.com",
        "http://ollama.example.com",
        "http://ollama.",
        "http://localhost.localdomain",
        "http://127.0.0.2",
        "http://0.0.0.0",
        "http://10.0.0.5",
        "http://user:pw@ollama",
        "ftp://ollama",
        "ollama",
        "http://ollama/api",
        "http://ollama/?x=1",
        "",
    ],
)
def test_other_hosts_are_refused_before_any_request(host: str) -> None:
    seen, handler = capture()
    with pytest.raises(OllamaError):
        OllamaClient(host, transport=httpx.MockTransport(handler))
    assert seen == []


def test_from_env_reads_the_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOST_ENV, "http://ollama")
    seen, handler = capture()
    c = OllamaClient.from_env(transport=httpx.MockTransport(handler))
    generate(c)
    assert seen[0].url.host == "ollama"


def test_from_env_refuses_a_disallowed_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(HOST_ENV, "http://example.com")
    with pytest.raises(OllamaError, match="not allowed"):
        OllamaClient.from_env(transport=httpx.MockTransport(ok()))


def test_from_env_without_the_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(HOST_ENV, raising=False)
    with pytest.raises(OllamaError, match=HOST_ENV):
        OllamaClient.from_env(transport=httpx.MockTransport(ok()))


def test_context_manager_closes_the_client() -> None:
    with client(ok()) as c:
        assert generate(c) == ANSWER
    with pytest.raises(RuntimeError):
        generate(c)
