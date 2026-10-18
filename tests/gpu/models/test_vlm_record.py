"""CLS-004.2.6: record the VLM classify and NSFW-level requests against the real `models.vlm_safe`.

The scenario is the classify node's integration scenario (`tests/unit/models/vlm_scenario.py`):
benign synthetic pictures, coined category names and hints. Without `--record-ollama` this runs
against the real model and asserts structure only; with it, every request is written under
`tests/recordings/models/` (see `tests/recordings/README.md`).

Prerequisites, named on failure (never skipped): the compose `ollama` service of this project
is running and `models.vlm_safe` is pulled (`make models`).
"""

from collections.abc import Callable

import httpx
import pytest

from classifier.config import NsfwLevel, load_config
from classifier.models.ollama import OllamaClient, OllamaError
from classifier.models.vlm_classify import VlmUnanswered, vlm_classify
from tests.unit.models.vlm_scenario import (
    FORMATS,
    HINTS,
    SCENARIO_LABELS,
    TOPICS,
    open_scenario_image,
)

PREREQS = (
    "start the compose `ollama` service for this project "
    "(docker compose -p <project> up -d ollama) and pull models.vlm_safe (make models)"
)


@pytest.mark.parametrize("label", SCENARIO_LABELS)
def test_record_the_scenario(
    label: str, ollama_transport: Callable[[str], httpx.BaseTransport]
) -> None:
    model = load_config().models.vlm_safe
    image = open_scenario_image(label)
    with OllamaClient.from_env(transport=ollama_transport("models")) as client:
        try:
            answer = vlm_classify(
                client,
                model,
                image,
                hint=HINTS.get(label),
                formats=list(FORMATS),
                topics=list(TOPICS),
            )
        except (OllamaError, VlmUnanswered) as exc:
            pytest.fail(f"{type(exc).__name__}: {exc}; prerequisites: {PREREQS}")
    assert answer.format in (*FORMATS, "unsorted")
    assert answer.topic is None or answer.topic in TOPICS
    assert isinstance(answer.level, NsfwLevel)
