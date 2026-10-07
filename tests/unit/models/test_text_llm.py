"""MOD-001.2.2: `detect_entities` through `httpx.MockTransport` only (never live Ollama).

Synthetic strings only (SAN-001.D10). Hosts carry no port (tier audit, TST-002.2).
"""

import json
from collections.abc import Callable

import httpx
import pytest

from classifier.models.ollama import OllamaClient, OllamaError
from classifier.models.text_llm import (
    ENTITY_LABELS,
    ENTITY_PROMPT,
    Entity,
    detect_entities,
    entity_prompt,
)

TEXT = "Zorvane_Quillby_at_Brakmoor_Works_2031-04-05_0007"
ALL = ENTITY_LABELS
Handler = Callable[[httpx.Request], httpx.Response]


def answering(answer: object, seen: list[dict] | None = None) -> OllamaClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(json.loads(request.content))
        return httpx.Response(200, json={"response": json.dumps(answer)})

    return OllamaClient("http://ollama", transport=httpx.MockTransport(handler))


def detect(answer: object, text: str = TEXT, labels=ALL, seen=None) -> list[Entity]:
    return detect_entities(text, labels, client=answering(answer, seen), model="tag:1b")


def ents(*pairs: tuple[str, str]) -> dict:
    return {"entities": [{"text": t, "label": lb} for t, lb in pairs]}


def test_request_uses_the_prompt_front_matter() -> None:
    seen: list[dict] = []
    detect(ents(), seen=seen)
    (body,) = seen
    p = entity_prompt()
    assert p.version == ENTITY_PROMPT
    assert body["model"] == "tag:1b"
    assert body["format"] == p.output_schema
    assert body["options"] == {"temperature": 0.0, "seed": p.seed}
    assert body["keep_alive"] == p.keep_alive
    assert "think" not in body  # MOD-001.D2: the tag ignores think=false
    assert "images" not in body
    assert TEXT in body["prompt"]


def test_labels_render_in_a_fixed_order() -> None:
    a: list[dict] = []
    b: list[dict] = []
    detect(ents(), labels=["LOCATION", "PERSON"], seen=a)
    detect(ents(), labels=("PERSON", "LOCATION", "PERSON"), seen=b)
    assert a[0]["prompt"] == b[0]["prompt"]
    assert "only these:\n- PERSON\n- LOCATION\n\n" in a[0]["prompt"]


def test_entities_in_order_of_appearance() -> None:
    got = detect(ents(("Brakmoor_Works", "ORG"), ("Zorvane_Quillby", "PERSON")))
    assert got == [Entity("Zorvane_Quillby", "PERSON"), Entity("Brakmoor_Works", "ORG")]


def test_span_not_in_input_is_dropped() -> None:
    got = detect(
        ents(
            ("Zorvane Quillby", "PERSON"),  # separator changed
            ("zorvane_quillby", "PERSON"),  # case changed
            ("Ostrela", "LOCATION"),  # invented
            ("Brakmoor", "LOCATION"),
        )
    )
    assert got == [Entity("Brakmoor", "LOCATION")]


def test_label_not_asked_for_is_dropped() -> None:
    got = detect(
        ents(("Zorvane_Quillby", "PERSON"), ("Brakmoor_Works", "ORG"), ("Works", "DATE")),
        labels=["PERSON"],
    )
    assert got == [Entity("Zorvane_Quillby", "PERSON")]


def test_duplicates_and_blank_spans_collapse() -> None:
    got = detect(
        ents(("Brakmoor", "LOCATION"), ("Brakmoor", "LOCATION"), ("", "ORG"), ("_ ", "ORG"))
    )
    assert got == [Entity("Brakmoor", "LOCATION")]


def test_empty_answer_is_valid() -> None:
    assert detect(ents()) == []


@pytest.mark.parametrize(("text", "labels"), [("", ALL), ("   ", ALL), (TEXT, [])])
def test_nothing_to_do_makes_no_call(text: str, labels: list[str]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no call expected")

    client = OllamaClient("http://ollama", transport=httpx.MockTransport(handler))
    assert detect_entities(text, labels, client=client, model="tag:1b") == []


def test_unknown_label_requested() -> None:
    with pytest.raises(ValueError, match="unknown entity labels"):
        detect(ents(), labels=["PERSON", "EMAIL"])


@pytest.mark.parametrize(
    "answer",
    [
        {},
        {"entities": "Zorvane_Quillby"},
        {"entities": ["Zorvane_Quillby"]},
        {"entities": [{"text": "Zorvane_Quillby"}]},
        {"entities": [{"text": 3, "label": "PERSON"}]},
        {"entities": [{"text": "Zorvane_Quillby", "label": None}]},
    ],
)
def test_malformed_answer_fails_closed_without_leaking(answer: object) -> None:
    with pytest.raises(OllamaError, match="entity answer") as info:
        detect(answer)
    assert "Zorvane" not in str(info.value)
    assert "Brakmoor" not in str(info.value)
