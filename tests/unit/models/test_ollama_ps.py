"""MOD-003.1: `OllamaClient.loaded_models()` reads `/api/ps`, through `httpx.MockTransport` only.

Hosts carry no port on purpose: the tier audit flags the Ollama port in a unit test (TST-002.2).
The model tags are synthetic coinages.
"""

import dataclasses
from collections.abc import Callable

import httpx
import pytest

from classifier.models.ollama import (
    PS_PATH,
    PS_TIMEOUT,
    LoadedModel,
    OllamaClient,
    OllamaError,
)

HOST = "http://ollama"
SECRET = "qorvexsecret zhyndelmarker"

Handler = Callable[[httpx.Request], httpx.Response]

TWO_MODELS = {
    "models": [
        {
            "name": "qorvex:1b",
            "model": "qorvex:1b",
            "size": 3_000_000_000,
            "digest": "0" * 64,
            "details": {"family": "qorvex"},
            "expires_at": "2026-11-10T04:00:00Z",
            "size_vram": 2_500_000_000,
        },
        {"name": "zhyndel:2b", "size_vram": 0},
    ]
}


def client(handler: Handler, host: str = HOST) -> OllamaClient:
    return OllamaClient(host, transport=httpx.MockTransport(handler))


def answer(body: object, status: int = 200) -> Handler:
    return lambda request: httpx.Response(status, json=body)


def capture(body: object = TWO_MODELS) -> tuple[list[httpx.Request], Handler]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=body)

    return seen, handler


def raising(exc_type: type[httpx.HTTPError]) -> Handler:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_type(SECRET, request=request)

    return handler


def test_request_is_a_bodyless_get_on_api_ps() -> None:
    seen, handler = capture()
    client(handler).loaded_models()
    (request,) = seen
    assert request.method == "GET"
    assert request.url == httpx.URL(HOST + PS_PATH)
    assert request.content == b""


def test_request_uses_the_short_status_timeout() -> None:
    # MOD-003.D1: not the client's model-load timeout.
    seen, handler = capture()
    client(handler).loaded_models()
    assert PS_TIMEOUT == 5.0
    assert all(value == PS_TIMEOUT for value in seen[0].extensions["timeout"].values())


def test_parses_the_models_in_order_and_ignores_extra_fields() -> None:
    assert client(answer(TWO_MODELS)).loaded_models() == [
        LoadedModel(name="qorvex:1b", size_vram=2_500_000_000),
        LoadedModel(name="zhyndel:2b", size_vram=0),
    ]


def test_nothing_loaded_is_an_empty_list_not_none() -> None:
    assert client(answer({"models": []})).loaded_models() == []


def test_loaded_model_is_frozen() -> None:
    model = LoadedModel(name="qorvex:1b", size_vram=1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        model.size_vram = 2  # type: ignore[misc]


@pytest.mark.parametrize(
    "exc_type",
    [httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout, httpx.DecodingError],
)
def test_a_transport_failure_is_none(exc_type: type[httpx.HTTPError]) -> None:
    assert client(raising(exc_type)).loaded_models() is None


def entry(**fields: object) -> dict:
    return {"models": [{"name": "qorvex:1b", "size_vram": 1} | fields]}


def without(key: str) -> dict:
    body = entry()
    del body["models"][0][key]
    return body


@pytest.mark.parametrize(
    "handler",
    [
        answer({"error": "synthetic"}, status=404),
        answer({"models": []}, status=500),
        lambda request: httpx.Response(200, text="not json"),
        lambda request: httpx.Response(200, content=b"\xff\xfe\x00"),
        answer(["models"]),
        answer({}),
        answer({"models": None}),
        answer({"models": {"name": "qorvex:1b", "size_vram": 1}}),
        answer({"models": ["qorvex:1b"]}),
        answer(without("name")),
        answer(entry(name="")),
        answer(entry(name=7)),
        answer(without("size_vram")),
        answer(entry(size_vram="1")),
        answer(entry(size_vram=1.5)),
        answer(entry(size_vram=True)),
        answer(entry(size_vram=-1)),
        # One bad entry makes the whole answer None, not a partial list.
        answer({"models": [{"name": "qorvex:1b", "size_vram": 1}, {"name": "zhyndel:2b"}]}),
    ],
)
def test_a_bad_status_or_body_is_none(handler: Handler) -> None:
    assert client(handler).loaded_models() is None


def test_failure_keeps_no_exception_text() -> None:
    # The planted secret is in the transport error the fake raises; it is served, then dropped.
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError(SECRET, request=request)

    result = client(handler).loaded_models()
    assert len(seen) == 1
    assert result is None
    assert SECRET not in repr(result)


def test_a_disallowed_host_is_still_refused_before_any_request() -> None:
    seen, handler = capture()
    with pytest.raises(OllamaError):
        client(handler, host="http://example.com")
    assert seen == []


def test_the_client_still_works_after_a_failed_status_read() -> None:
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError(SECRET, request=request)
        return httpx.Response(200, json={"models": []})

    c = client(handler)
    assert c.loaded_models() is None
    assert c.loaded_models() == []
