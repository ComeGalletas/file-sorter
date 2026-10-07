"""Text-LLM tasks on top of the Ollama client (MOD-001.2, R-SAN-3, R-SAN-4, P-2).

`detect_entities` finds PERSON, ORG and LOCATION spans in text that has already passed the
sanitizer's literal and regex rules. The caller passes the client and the model tag
(`models.text_llm`); the sampling options, `keep_alive` and the output schema come from the
prompt file's front matter (MOD-001.D1).

The answer is filtered, never trusted (MOD-001.D2): a span that isn't literally in the input
and a label that wasn't asked for are dropped. An answer that doesn't have the schema's shape
raises `OllamaError`, so the sanitizer fails closed (SAN-001.D2). Errors never carry the text
or the answer.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache

from classifier.models.ollama import OllamaClient, OllamaError, _prompt_hash
from classifier.models.prompts import Prompt, load_prompt

ENTITY_PROMPT = "sanitize_entity_v1"
ENTITY_LABELS = ("PERSON", "ORG", "LOCATION")


@dataclass(frozen=True)
class Entity:
    """One detected span, exactly as it appears in the input."""

    text: str
    label: str


@cache
def entity_prompt() -> Prompt:
    """The entity prompt; its `version` is what a stage records on the ledger (R-CAP-3)."""
    return load_prompt(ENTITY_PROMPT)


def _canonical_labels(labels: Iterable[str]) -> tuple[str, ...]:
    asked = set(labels)
    unknown = asked - set(ENTITY_LABELS)
    if unknown:
        raise ValueError(f"unknown entity labels {sorted(unknown)}; allowed: {ENTITY_LABELS}")
    # A fixed order, so the same request renders the same prompt whatever the caller's order.
    return tuple(label for label in ENTITY_LABELS if label in asked)


def detect_entities(
    text: str,
    labels: Iterable[str],
    *,
    client: OllamaClient,
    model: str,
    prompt: Prompt | None = None,
) -> list[Entity]:
    """The entities of the requested `labels` in `text`, in order of first appearance."""
    wanted = _canonical_labels(labels)
    if not text.strip() or not wanted:
        return []
    prompt = prompt or entity_prompt()
    answer = client.generate_json(
        model=model,
        prompt=prompt.render(labels="\n".join(f"- {label}" for label in wanted), text=text),
        schema=prompt.output_schema,
        options=prompt.options,
        keep_alive=prompt.keep_alive,
        think=prompt.think,
        raw=prompt.raw,
    )
    where = f"model {model!r}, text {_prompt_hash(text)}"
    items = answer.get("entities")
    if not isinstance(items, list):
        raise OllamaError(f"entity answer has no `entities` list ({where})")
    found: dict[Entity, int] = {}
    for item in items:
        if not (
            isinstance(item, dict)
            and isinstance(item.get("text"), str)
            and isinstance(item.get("label"), str)
        ):
            raise OllamaError(f"entity answer has a malformed item ({where})")
        span, label = item["text"], item["label"]
        # MOD-001.D2: drop what wasn't asked for and what isn't literally in the input.
        if label not in wanted or not span.strip() or span not in text:
            continue
        entity = Entity(span, label)
        found.setdefault(entity, text.index(span))
    return sorted(found, key=lambda e: (found[e], -len(e.text), e.label))
