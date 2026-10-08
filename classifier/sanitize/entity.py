"""The `entity` rule: MOD-001.2's detector as the callable `sanitize_text` takes (SAN-001.3).

`EntityDetector` sees text that has already passed the literal and regex rules (R-SAN-4),
so it holds raw values. Every failure of the detector or its client becomes one
`EntityUnavailableError`, with fixed text and nothing chained, and the file fails closed
(SAN-001.D2, P-2). Nothing here logs, and no text, span or label reaches a `repr` or an error.

Only the local backend exists in M2: `sanitizer.backend: claude` fails fast (SAN-001.D6).
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from classifier.config import Config
from classifier.models.ollama import OllamaClient
from classifier.models.text_llm import Entity, detect_entities
from classifier.sanitize.rules import SanitizeConfigError

ENTITY_REASON = "sanitize_entity_unavailable"  # SAN-001.D2

Detect = Callable[..., object]


class EntityUnavailableError(Exception):
    """Entity detection failed or answered out of shape: the file fails closed (SAN-001.D2).

    The message is fixed text: never the text, a span, a label or the cause's message.
    """

    reason = ENTITY_REASON

    def __init__(self) -> None:
        super().__init__(f"entity detection failed: {ENTITY_REASON}")


def check_backend(config: Config) -> None:
    """Refuse any sanitizer backend but `local` (SAN-001.D6). `sanitizer.ocr` is SAN-001.4's."""
    if config.sanitizer.backend != "local":
        raise SanitizeConfigError(
            "sanitizer.backend must be local: the claude backend is not available in M2"
        )


@dataclass(frozen=True)
class EntityDetector:
    """`entity(text, labels) -> [(span, label)]` on top of `detect_entities` (MOD-001.2).

    Its repr shows the model tag only. `detect` is replaced in unit tests by a fake.
    """

    client: OllamaClient = field(repr=False)
    model: str
    detect: Detect = field(default=detect_entities, repr=False)

    def __call__(self, text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        wanted = tuple(labels)
        # `except Exception` only: the replay's RecordingError (a BaseException) and
        # KeyboardInterrupt escape. The typed error is raised after the block, so neither
        # __cause__ nor __context__ carries the original, whose message may quote the text.
        failed = False
        pairs = None
        try:
            found = self.detect(text, wanted, client=self.client, model=self.model)
            pairs = _pairs(found)
        except Exception:
            failed = True
        if failed or pairs is None:
            raise EntityUnavailableError()
        # Defence in depth (MOD-001.D2 filters too): only asked labels, only spans in the text.
        return [
            (span, label)
            for span, label in pairs
            if label in wanted and span.strip() and span in text
        ]


def _pairs(found: object) -> list[tuple[str, str]] | None:
    """The detector's answer as pairs, or None when it isn't a list of string `Entity`s."""
    if not isinstance(found, list):
        return None
    pairs = []
    for item in found:
        if not (
            isinstance(item, Entity) and isinstance(item.text, str) and isinstance(item.label, str)
        ):
            return None
        pairs.append((item.text, item.label))
    return pairs


def entity_detector(config: Config, client: OllamaClient) -> EntityDetector:
    """The `entity` callable for `sanitize_name`, on `models.text_llm` (R-SAN-3, SAN-001.D6)."""
    check_backend(config)
    return EntityDetector(client=client, model=config.models.text_llm)
