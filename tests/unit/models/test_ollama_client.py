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


def test_request_is_text_only() -> None:
    seen, handler = capture()
    generate(client(handler))
    assert "images" not in json.loads(seen[0].content)


@pytest.mark.parametrize("think", [False, True])
def test_think_is_sent_only_when_set(think: bool) -> None:
    seen, handler = capture()
    generate(client(handler), think=think)
    assert json.loads(seen[0].content)["think"] is think


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
