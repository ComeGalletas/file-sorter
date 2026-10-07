"""The Ollama text client (MOD-001.1, R-MOD-1, P-3, C-13).

Every Ollama call in the app goes through `OllamaClient`. It talks to the compose `ollama`
service (or localhost) over `httpx` and refuses any other host. Text only: the request never
carries an `images` field.

Nothing about the model is hard-coded here. The caller passes the tag (`models.text_llm`) and
the sampling options and `keep_alive` from the prompt file's front matter (MOD-001.D1).

The `transport` argument is a plain `httpx.BaseTransport`: tests pass an `httpx.MockTransport`,
and the default tiers pass the recorded-response replay (TST-005.1), so they never reach Ollama.

Errors never carry the prompt or the model's answer, only a short hash of the prompt.
"""

import hashlib
import json
import os
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Self

import httpx

HOST_ENV = "OLLAMA_HOST"
GENERATE_PATH = "/api/generate"
# MOD-001.D4: the first call after a model swap loads a 6–9 GB model (R-MOD-1).
DEFAULT_TIMEOUT = 300.0
# The compose service and localhost, exactly (CLAUDE.md network rule). Never widen this.
ALLOWED_HOSTS = frozenset({"ollama", "localhost", "127.0.0.1", "::1"})


class OllamaError(Exception):
    """An Ollama call failed: refused host, connection, timeout, HTTP status or bad JSON."""


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:8]


def check_host(host: str) -> httpx.URL:
    """The parsed host URL, or `OllamaError` unless it is the compose service or localhost."""
    try:
        url = httpx.URL(host)
    except httpx.InvalidURL as exc:
        raise OllamaError(f"invalid Ollama host URL: {exc}") from None
    if url.scheme not in {"http", "https"}:
        raise OllamaError(f"Ollama host must use http or https, not {url.scheme!r}")
    if url.userinfo:
        raise OllamaError("Ollama host must not carry credentials")
    if url.host not in ALLOWED_HOSTS:
        raise OllamaError(
            f"Ollama host {url.host!r} is not allowed: only {', '.join(sorted(ALLOWED_HOSTS))}"
        )
    if url.path not in {"", "/"} or url.query or url.fragment:
        raise OllamaError("Ollama host must be a bare scheme://host[:port]")
    return url


class OllamaClient:
    """A text client for Ollama's `/api/generate`, with structured JSON output."""

    def __init__(
        self,
        host: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        # The check runs even with a transport, so a test transport cannot hide a bad host.
        self.host = check_host(host)
        self._http = httpx.Client(base_url=self.host, transport=transport, timeout=timeout)

    @classmethod
    def from_env(
        cls, transport: httpx.BaseTransport | None = None, timeout: float = DEFAULT_TIMEOUT
    ) -> Self:
        """A client for `OLLAMA_HOST` (compose sets it). There is no default URL."""
        host = os.environ.get(HOST_ENV)
        if not host:
            raise OllamaError(f"{HOST_ENV} is not set")
        return cls(host, transport=transport, timeout=timeout)

    def generate_json(
        self,
        model: str,
        prompt: str,
        schema: Mapping[str, Any],
        options: Mapping[str, Any],
        keep_alive: str | int,
        think: bool | None = None,
    ) -> dict[str, Any]:
        """Run `prompt` on `model` and return its answer, constrained to the JSON `schema`."""
        body: dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "format": dict(schema),
            "options": dict(options),
            "keep_alive": keep_alive,
            "stream": False,
        }
        if think is not None:
            body["think"] = think
        where = f"model {model!r}, prompt {_prompt_hash(prompt)}"
        try:
            response = self._http.post(GENERATE_PATH, json=body)
        except httpx.TimeoutException as exc:
            raise OllamaError(f"Ollama timed out ({where}): {type(exc).__name__}") from exc
        except httpx.TransportError as exc:
            raise OllamaError(f"cannot reach Ollama ({where}): {type(exc).__name__}") from exc
        if response.is_error:
            raise OllamaError(f"Ollama returned HTTP {response.status_code} ({where})")
        try:
            payload = response.json()
        except ValueError:
            raise OllamaError(f"Ollama sent a body that is not JSON ({where})") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("response"), str):
            raise OllamaError(f"Ollama's body has no text `response` field ({where})")
        try:
            answer = json.loads(payload["response"])
        except ValueError:
            raise OllamaError(f"Ollama's answer is not valid JSON ({where})") from None
        if not isinstance(answer, dict):
            raise OllamaError(f"Ollama's answer is not a JSON object ({where})")
        return answer

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()
