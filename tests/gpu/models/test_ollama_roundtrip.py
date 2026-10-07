"""MOD-001.1.2: the Ollama client against the real `ollama` service, synthetic text only.

Prerequisites, named on failure (CLAUDE.md §3, never skipped): the compose `ollama` service is
running in this compose project, and `models.text_llm` is pulled (`make models`).
Temperature 0 and a fixed seed; `keep_alive: 0` unloads the model afterwards (R-MOD-1).
"""

import pytest

from classifier.config import load_config
from classifier.models.ollama import OllamaClient, OllamaError

SCHEMA = {
    "type": "object",
    "properties": {"word": {"type": "string", "enum": ["alpha", "beta"]}},
    "required": ["word"],
}
OPTIONS = {"temperature": 0, "seed": 7}
PREREQS = (
    "start the compose `ollama` service for this project "
    "(docker compose -p <project> up -d ollama) and pull models.text_llm (make models)"
)


@pytest.fixture(scope="module")
def client():
    with OllamaClient.from_env() as c:
        yield c


def test_generate_json_round_trip(client: OllamaClient) -> None:
    model = load_config().models.text_llm
    try:
        answer = client.generate_json(
            model=model,
            prompt="Reply with the word alpha.",
            schema=SCHEMA,
            options=OPTIONS,
            keep_alive=0,
        )
    except OllamaError as exc:
        pytest.fail(f"{exc}; prerequisites: {PREREQS}")
    assert answer["word"] in {"alpha", "beta"}


def test_unknown_model_is_an_ollama_error(client: OllamaClient) -> None:
    with pytest.raises(OllamaError, match="HTTP 404"):
        client.generate_json(
            model="no-such-model:0b",
            prompt="Reply with the word alpha.",
            schema=SCHEMA,
            options=OPTIONS,
            keep_alive=0,
        )
