"""CLS-004.2.6: replay the recorded VLM requests through `vlm_classify`.

The recordings under `tests/recordings/models/` were made by `tests/gpu/models/test_vlm_record.py`
from the classify node's synthetic scenario. Replay is exact: a request the client no longer sends
the same way (prompt, enums, hint, frame pixels, options) misses its recording and fails. The
answers are the recorded ones, so only the structure is asserted.
"""

from collections.abc import Callable

import httpx
import pytest

from classifier.config import NsfwLevel, load_config
from classifier.models.classify_rules import VlmAnswer
from classifier.models.ollama import OllamaClient
from classifier.models.vlm_classify import vlm_classify
from tests.unit.models.vlm_scenario import (
    FORMATS,
    HINTS,
    SCENARIO_LABELS,
    TOPICS,
    open_scenario_image,
)


@pytest.mark.parametrize("label", SCENARIO_LABELS)
def test_the_recorded_scenario_replays(
    label: str, ollama_transport: Callable[[str], httpx.BaseTransport]
) -> None:
    model = load_config().models.vlm_safe
    with OllamaClient("http://ollama", transport=ollama_transport("models")) as client:
        answer = vlm_classify(
            client,
            model,
            open_scenario_image(label),
            hint=HINTS.get(label),
            formats=list(FORMATS),
            topics=list(TOPICS),
        )
    assert isinstance(answer, VlmAnswer)
    assert answer.format in (*FORMATS, "unsorted")
    assert answer.topic is None or answer.topic in TOPICS
    assert isinstance(answer.level, NsfwLevel)
