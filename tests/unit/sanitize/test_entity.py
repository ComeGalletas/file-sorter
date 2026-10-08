"""SAN-001.3: the entity rule on top of MOD-001.2's detector, failing closed (SAN-001.D2, D6).

A fake detector, or the real `detect_entities` on an `httpx.MockTransport`: never Ollama.
Synthetic strings only, and nothing is recorded (SAN-001.D10). Hosts carry no port (tier audit).
"""

import json
import logging
import traceback
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
import yaml

from classifier.config import Config
from classifier.models.ollama import OllamaClient, OllamaError
from classifier.models.text_llm import Entity
from classifier.sanitize.entity import (
    ENTITY_REASON,
    EntityDetector,
    EntityUnavailableError,
    check_backend,
    entity_detector,
)
from classifier.sanitize.exif import RESIDUAL_REASON
from classifier.sanitize.rules import (
    FILENAME,
    EntityRule,
    ExifSettings,
    LiteralRule,
    RegexRule,
    Rules,
    SanitizeConfigError,
    before_hash,
    sanitize_name,
    sanitize_text,
)

REPO = Path(__file__).resolve().parents[3]
KEY = b"00112233445566778899aabbccddeeff"
SECRET = "Qorvex Thimbledrop"  # made up; must never surface outside the returned spans
TEXT = f"{SECRET}_at_Brakmoor_Works_0007"


def client(handler: Callable[[httpx.Request], httpx.Response] | None = None) -> OllamaClient:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise AssertionError("the fake detector must not reach the transport")

    return OllamaClient("http://ollama", transport=httpx.MockTransport(handler or refuse))


class Fake:
    """A detector that records its calls and answers, or raises, as told."""

    def __init__(self, answer: object = (), raises: BaseException | None = None) -> None:
        self.answer = answer
        self.raises = raises
        self.calls: list[tuple[str, tuple[str, ...], str]] = []

    def __call__(self, text, labels, *, client, model):
        self.calls.append((text, tuple(labels), model))
        if self.raises is not None:
            raise self.raises
        return list(self.answer) if isinstance(self.answer, tuple) else self.answer


def detector(fake: Fake) -> EntityDetector:
    return EntityDetector(client=client(), model="tag:1b", detect=fake)


def rules(*extra) -> Rules:
    entity = EntityRule(id="ner", type="entity", labels=["PERSON", "ORG"], replace="[{label}]")
    return Rules(exif=ExifSettings(mode="strip_all"), rules=(*extra, entity), log_key=KEY)


def config(**sanitizer) -> Config:
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    data["sanitizer"].update(sanitizer)
    return Config.model_validate(data)


def assert_clean(error: BaseException) -> None:
    """Fixed text, nothing chained, and the secret nowhere in the whole traceback."""
    assert isinstance(error, EntityUnavailableError)
    assert error.reason == ENTITY_REASON == "sanitize_entity_unavailable"
    assert str(error) == "entity detection failed: sanitize_entity_unavailable"
    assert error.__cause__ is None
    assert error.__context__ is None
    shown = "".join(traceback.format_exception(error)) + repr(error)
    for word in SECRET.split():
        assert word not in shown


# --- the adapter --------------------------------------------------------------------------


def test_spans_pass_through_as_pairs() -> None:
    fake = Fake((Entity(SECRET, "PERSON"), Entity("Brakmoor_Works", "ORG")))
    got = detector(fake)(TEXT, ["PERSON", "ORG"])
    assert got == [(SECRET, "PERSON"), ("Brakmoor_Works", "ORG")]
    assert fake.calls == [(TEXT, ("PERSON", "ORG"), "tag:1b")]


@pytest.mark.parametrize(
    "entity",
    [
        Entity("Qorvex  Thimbledrop", "PERSON"),  # not literally in the text
        Entity("", "PERSON"),
        Entity("   ", "PERSON"),
        Entity(SECRET, "LOCATION"),  # a label that wasn't asked for
    ],
)
def test_spans_outside_the_text_or_the_labels_are_dropped(entity: Entity) -> None:
    assert detector(Fake((entity,)))(TEXT, ["PERSON", "ORG"]) == []


def test_no_entities_is_an_empty_list() -> None:
    assert detector(Fake())(TEXT, ["PERSON"]) == []


def test_repr_shows_the_model_only() -> None:
    fake = Fake((Entity(SECRET, "PERSON"),))
    adapter = detector(fake)
    adapter(TEXT, ["PERSON"])
    assert repr(adapter) == "EntityDetector(model='tag:1b')"


# --- failing closed (SAN-001.D2) ----------------------------------------------------------


@pytest.mark.parametrize(
    "raised",
    [
        OllamaError(f"cannot reach Ollama: {SECRET}"),
        TimeoutError(SECRET),
        ValueError(f"unknown entity labels [{SECRET!r}]"),
        RuntimeError(SECRET),
        UnicodeEncodeError("utf-8", SECRET, 0, 1, "surrogates not allowed"),
        KeyError(SECRET),
    ],
)
def test_any_detector_exception_becomes_one_unchained_error(raised: Exception) -> None:
    with pytest.raises(EntityUnavailableError) as info:
        detector(Fake(raises=raised))(TEXT, ["PERSON"])
    assert_clean(info.value)


@pytest.mark.parametrize(
    "answer",
    [
        None,
        {"entities": [{"text": SECRET, "label": "PERSON"}]},
        (SECRET,),
        ((SECRET, "PERSON"),),
        ({"text": SECRET, "label": "PERSON"},),
        (Entity(SECRET, "PERSON"), None),
        (Entity(42, "PERSON"),),  # type: ignore[arg-type]
        (Entity(SECRET, None),),  # type: ignore[arg-type]
        SECRET,
    ],
)
def test_an_answer_out_of_shape_fails_closed(answer: object) -> None:
    with pytest.raises(EntityUnavailableError) as info:
        detector(Fake(answer))(TEXT, ["PERSON"])
    assert_clean(info.value)


def test_base_exceptions_escape() -> None:
    # The replay's RecordingError is a BaseException: a missing recording must fail the test,
    # not pass as a fail-closed file (lead, #52).
    class Missing(BaseException):
        pass

    with pytest.raises(Missing):
        detector(Fake(raises=Missing()))(TEXT, ["PERSON"])
    with pytest.raises(KeyboardInterrupt):
        detector(Fake(raises=KeyboardInterrupt()))(TEXT, ["PERSON"])


def test_a_lone_surrogate_in_the_text_still_fails_with_the_typed_error() -> None:
    text = f"{SECRET}\udcff_0007"
    with pytest.raises(EntityUnavailableError) as info:
        detector(Fake(raises=UnicodeEncodeError("utf-8", text, 19, 20, "bad")))(text, ["PERSON"])
    assert_clean(info.value)
    assert detector(Fake((Entity(SECRET, "PERSON"),)))(text, ["PERSON"]) == [(SECRET, "PERSON")]


def test_nothing_is_logged_or_printed(caplog, capsys) -> None:
    caplog.set_level(logging.DEBUG)
    detector(Fake((Entity(SECRET, "PERSON"),)))(TEXT, ["PERSON"])
    with pytest.raises(EntityUnavailableError):
        detector(Fake(raises=OllamaError(SECRET)))(TEXT, ["PERSON"])
    out = capsys.readouterr()
    for word in SECRET.split():
        assert word not in caplog.text + out.out + out.err


# --- wired into sanitize_text / sanitize_name (R-SAN-4) -----------------------------------


def test_redacts_after_literal_and_regex_and_sees_only_their_output() -> None:
    literal = LiteralRule(id="who", type="literal", values=["Brakmoor"], replace="[L]")
    regex = RegexRule(id="num", type="regex", pattern=r"\d{4}", replace="[N]")
    fake = Fake((Entity(SECRET, "PERSON"), Entity("Works", "ORG")))
    clean, found = sanitize_text(TEXT, FILENAME, rules(literal, regex), detector(fake))
    assert clean == "[PERSON]_at_[L]_[ORG]_[N]"
    assert fake.calls == [(f"{SECRET}_at_[L]_Works_[N]", ("PERSON", "ORG"), "tag:1b")]
    assert [r.rule_id for r in found] == ["who", "num", "ner", "ner"]
    assert found[2].before_hash == before_hash(SECRET, KEY)
    assert all(SECRET not in repr(r) for r in found)


def test_a_failure_leaves_no_partly_redacted_name() -> None:
    fake = Fake(raises=OllamaError(SECRET))
    with pytest.raises(EntityUnavailableError) as info:
        sanitize_name(f"Trip_Brakmoor/{SECRET}.jpg", rules(), detector(fake))
    assert_clean(info.value)


# --- the real detector on a fake transport (pins MOD-001.2's signature and errors) --------


def ollama_answering(answer: object) -> OllamaClient:
    return client(lambda request: httpx.Response(200, json={"response": json.dumps(answer)}))


def test_the_real_detector_through_a_mock_transport() -> None:
    answer = {
        "entities": [{"text": SECRET, "label": "PERSON"}, {"text": "Velquor", "label": "ORG"}]
    }
    adapter = EntityDetector(client=ollama_answering(answer), model="tag:1b")
    assert adapter(TEXT, ["PERSON", "ORG"]) == [(SECRET, "PERSON")]


def _raise(exc: Exception) -> Callable[[httpx.Request], httpx.Response]:
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc

    return handler


@pytest.mark.parametrize(
    "handler",
    [
        _raise(httpx.ConnectError(SECRET)),
        _raise(httpx.ReadTimeout(SECRET)),
        lambda request: httpx.Response(500, text=SECRET),
        lambda request: httpx.Response(200, text=SECRET),
        lambda request: httpx.Response(200, json={"response": SECRET}),
        lambda request: httpx.Response(200, json={"response": "{}"}),
        lambda request: httpx.Response(200, json={"response": json.dumps({"entities": [SECRET]})}),
        lambda request: httpx.Response(
            200, json={"response": '{"entities": []}', "done_reason": "length"}
        ),
    ],
    ids=[
        "connect",
        "timeout",
        "http-500",
        "not-json",
        "answer-not-json",
        "no-list",
        "bad-item",
        "cut-off",
    ],
)
def test_the_real_detector_fails_closed(handler) -> None:
    adapter = EntityDetector(client=client(handler), model="tag:1b")
    with pytest.raises(EntityUnavailableError) as info:
        adapter(TEXT, ["PERSON"])
    assert_clean(info.value)


# --- the backend (SAN-001.D6) -------------------------------------------------------------


def test_local_backend_builds_a_detector_on_models_text_llm() -> None:
    cfg = config(backend="local")
    adapter = entity_detector(cfg, client())
    assert adapter.model == cfg.models.text_llm


def test_claude_backend_fails_fast_naming_the_key() -> None:
    with pytest.raises(SanitizeConfigError, match=r"sanitizer\.backend") as info:
        entity_detector(config(backend="claude"), client())
    assert info.value.__cause__ is None and info.value.__context__ is None
    check_backend(config(backend="local"))


def test_the_two_fail_closed_reasons_are_distinct() -> None:
    # SAN-001.4 maps both to `error` (SAN-001.D2).
    assert {ENTITY_REASON, RESIDUAL_REASON} == {
        "sanitize_entity_unavailable",
        "sanitize_metadata_residual",
    }
