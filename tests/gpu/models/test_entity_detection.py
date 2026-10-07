"""MOD-001.2: `detect_entities` against the real `ollama` service, synthetic strings only.

Prerequisites, named on failure (CLAUDE.md §3, never skipped): the compose `ollama` service is
running in this compose project, and `models.text_llm` is pulled (`make models`).
Temperature 0 and a fixed seed come from the prompt's front matter (MOD-001.D1).

Every name here is fictional (SAN-001.D10). The calls go through a recorder transport that
keeps each request and answer. The last test checks them against `tests/recordings/models/`;
with `RECORD_OLLAMA=1` it writes them instead (MOD-001.2.5):

    docker compose -p <project> --profile test run --rm -e RECORD_OLLAMA=1 test \
        pytest -m gpu tests/gpu/models/test_entity_detection.py

Format (TST-005.D3, D5): one `<key>.json` per request holding `{"request", "response"}`, where
`key` is the SHA-256 of the canonical request `{model, prompt, format, options, think?, raw?}`
as compact, key-sorted JSON (`keep_alive` and `stream` excluded). `response` keeps the body's
stable fields only (no durations, timestamps or token context). Until TST-005.1's replay lands,
`recording_key` is this task's copy of that rule.

`SANITIZE_STRINGS` are recorded for SAN-001.4's integration test: synthetic file stems it can
seed so its entity calls replay. All three labels are asked for, in ENTITY_LABELS order.
"""

import hashlib
import json
import os
from pathlib import Path

import httpx
import pytest

from classifier.config import load_config
from classifier.models.ollama import OllamaClient, OllamaError
from classifier.models.text_llm import ENTITY_LABELS, Entity, detect_entities

RECORDINGS = Path(__file__).resolve().parents[2] / "recordings" / "models"
RECORD_ENV = "RECORD_OLLAMA"
CANONICAL = ("model", "prompt", "format", "options")
CANONICAL_IF_SENT = ("think", "raw")
KEPT_RESPONSE_FIELDS = ("model", "response", "done", "done_reason")
PREREQS = (
    "start the compose `ollama` service for this project "
    "(docker compose -p <project> up -d ollama) and pull models.text_llm (make models)"
)

# (text, [(seeded span, label)]): every letter of each seeded span must be redacted, and every
# returned span that touches it must carry its label.
ENTITY_CASES = [
    ("Zorvane_Quillby_2031-04-05_0007", [("Zorvane_Quillby", "PERSON")]),
    (
        "Mirelda-Toskan at Brakmoor Harbour",
        [("Mirelda-Toskan", "PERSON"), ("Brakmoor Harbour", "LOCATION")],
    ),
    (
        "Quillfen_Robotics_offsite_Velkarra",
        [("Quillfen_Robotics", "ORG"), ("Velkarra", "LOCATION")],
    ),
    ("Durnhollow Athletic Club team photo 12", [("Durnhollow Athletic Club", "ORG")]),
    ("birthday_Oskarth_Venmire_party", [("Oskarth_Venmire", "PERSON")]),
    (
        "trip.to.Ostrela.Bay.with.Tamsin.Druvel",
        [("Ostrela.Bay", "LOCATION"), ("Tamsin.Druvel", "PERSON")],
    ),
]
NO_ENTITY = [
    "IMG_20310405_123456",
    "DSC00421-edit",
    "Screenshot 2031-04-05 at 10.15.32",
    "holiday_beach_final_v2",
    "scan_0042_copy",
    "PXL_20310101_000102345.MP",
]
SANITIZE_STRINGS = [
    "Velric_Haldric_2031-04-05_0007",
    "Saltreach Rowing Club regatta 03",
    "Ostrela_Bay_sunset_0012",
    "Ysolde Kestrand at Corrowmere",
    "IMG_20310405_0001",
]


def recording_key(body: dict) -> str:
    """The SHA-256 of the canonical request (TST-005.D3, D5)."""
    canonical = {k: body[k] for k in CANONICAL}
    canonical |= {k: body[k] for k in CANONICAL_IF_SENT if k in body}
    text = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Recorder(httpx.BaseTransport):
    """Forwards to the real service and keeps every successful request and answer."""

    def __init__(self) -> None:
        self._inner = httpx.HTTPTransport()
        self.seen: dict[str, dict] = {}

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        response = self._inner.handle_request(request)
        response.read()
        if response.status_code == 200:
            body = json.loads(request.content)
            payload = response.json()
            kept = {k: payload[k] for k in KEPT_RESPONSE_FIELDS if k in payload}
            self.seen[recording_key(body)] = {"request": body, "response": kept}
        return response

    def close(self) -> None:
        self._inner.close()


@pytest.fixture(scope="module")
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture(scope="module")
def detect(recorder: Recorder):
    model = load_config().models.text_llm
    with OllamaClient.from_env(transport=recorder) as client:

        def run(text: str, labels=ENTITY_LABELS) -> list[Entity]:
            try:
                return detect_entities(text, labels, client=client, model=model)
            except OllamaError as exc:
                pytest.fail(f"{exc}; prerequisites: {PREREQS}")

        yield run


def _overlapping(text: str, span: str, found: list[Entity]) -> tuple[list[Entity], bool]:
    start = text.index(span)
    seeded = set(range(start, start + len(span)))
    covered: set[int] = set()
    touching = []
    for e in found:
        at = text.find(e.text)
        while at != -1:
            idx = set(range(at, at + len(e.text)))
            covered |= idx
            if idx & seeded and e not in touching:
                touching.append(e)
            at = text.find(e.text, at + 1)
    letters = {i for i in seeded if text[i].isalpha()}
    return touching, letters <= covered


@pytest.mark.parametrize(("text", "seeded"), ENTITY_CASES, ids=[c[0] for c in ENTITY_CASES])
def test_seeded_entities_are_found(detect, text: str, seeded: list[tuple[str, str]]) -> None:
    found = detect(text)
    for span, label in seeded:
        touching, covered = _overlapping(text, span, found)
        assert covered, f"{span!r} would survive redaction: {found}"
        assert {e.label for e in touching} == {label}, f"{span!r}: {found}"


@pytest.mark.parametrize("text", NO_ENTITY)
def test_plain_names_are_left_alone(detect, text: str) -> None:
    assert detect(text) == []


def test_only_requested_labels_come_back(detect) -> None:
    found = detect("Mirelda-Toskan at Brakmoor Harbour", labels=["PERSON"])
    assert found and {e.label for e in found} == {"PERSON"}


def test_same_answer_twice(detect) -> None:
    text = ENTITY_CASES[2][0]
    assert detect(text) == detect(text)


@pytest.mark.parametrize("text", SANITIZE_STRINGS)
def test_sanitize_strings_answer(detect, text: str) -> None:
    detect(text)  # recorded for SAN-001.4; a shape error would already fail here


def test_recordings_match_live(recorder: Recorder) -> None:
    """Last in the module: every call above has its recording, with the same answer."""
    assert recorder.seen, "no calls were recorded"
    if os.environ.get(RECORD_ENV) == "1":
        RECORDINGS.mkdir(parents=True, exist_ok=True)
        for key, entry in recorder.seen.items():
            text = json.dumps(entry, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
            (RECORDINGS / f"{key}.json").write_text(text, encoding="utf-8", newline="\n")
        return
    for key, entry in recorder.seen.items():
        path = RECORDINGS / f"{key}.json"
        assert path.is_file(), f"no recording {key}; re-run with {RECORD_ENV}=1"
        recorded = json.loads(path.read_text(encoding="utf-8"))
        assert recorded == entry, f"recording {key} differs from the live answer"
