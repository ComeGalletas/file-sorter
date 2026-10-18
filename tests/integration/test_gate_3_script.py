"""TST-008.3.4, .3.6: gate 3 end to end on synthetic images, the real nodes and replayed vision.

Ingest, sanitize and classify are the real nodes (CLS-002.2) in a fresh migrated schema. The
pictures are the four benign synthetic ones of the classify scenario, so TST-008.1's replay
under tests/recordings/graph/ answers every SigLIP request. The adult cases use `NumericGate`,
a double that returns plain numbers for `nsfw_scores` (flat pictures never score as adult on the
real gate; lead ruling, #99): no content is made or described, and a row's `adult` is a label
column and a ledger `branch` is a string. The gate's thresholds here are the test ones of the
classify scenario, never the tuned ones. The real fixtures only run at `make gate-3` (TST-004).

Labels are derived from what the node wrote on a first pass, so this test proves the wiring:
vocabularies, label matching, the runner and the output. The measures themselves are proved on
plain numbers in tests/unit/gate/.

The classify node asks a scripted Ollama (`ScriptedVlm`): the level call rates the one picture
the double flags as `nudity` and the rest `safe`, and the node writes `files.nsfw_level` itself
(CLS-004.4). The gate script has no Ollama seam, so the test wraps `run` to pass the transport.
The labels stay 7-column, which also covers a labels file without the optional level column.
"""

import importlib.util
import re
from pathlib import Path

import numpy as np
import pytest
import yaml

from classifier.config import load_config
from classifier.sanitize.rules import LOG_KEY_ENV
from tests.db.db_support import require_db_dsn
from tests.integration.classify_support import LABELS, REPO, ScriptedVlm, make_image

SCRIPT = REPO / "scripts" / "gate_3.py"
_spec = importlib.util.spec_from_file_location("gate_3_it", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_3)

RULES = """
exif: {mode: strip_all}
rules:
  - {id: mine, type: literal, values: ["Zyxwq Plonk"], replace: "[PERSON]"}
"""
HEADER = "file,format,topic,adult,reference,subject,tags\n"
NAMES = dict(
    zip(LABELS, ("a-secret.png", "b-secret.png", "c-secret.png", "d-secret.png"), strict=True)
)
FLAGGED = "a-secret.png"  # the double reports this one as adult; a number, not a picture


class NumericGate:
    """The replay for embeddings and parameters; `nsfw_scores` returns plain numbers."""

    def __init__(self, replay) -> None:
        self._replay = replay

    def __getattr__(self, name: str):
        return getattr(self._replay, name)

    def nsfw_scores(self, images) -> np.ndarray:
        red = [1.0 if image.getpixel((0, 0)) == (200, 30, 30) else 0.0 for image in images]
        return np.array(red, dtype=np.float32)


@pytest.fixture(autouse=True)
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(LOG_KEY_ENV, "00112233445566778899aabbccddeeff")
    monkeypatch.setenv("DB_DSN", require_db_dsn())
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama:11434")
    data = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    config = tmp_path / "config-test.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    monkeypatch.setattr(gate_3, "CONFIG", config)
    # gate_3 imports `run` when it is called, so this wrapper adds the scripted Ollama to it.
    import classifier.graph.run as graph_run

    real, ollama = graph_run.run, ScriptedVlm()
    monkeypatch.setattr(
        graph_run,
        "run",
        lambda config, **kw: real(config, ollama_transport=ollama.transport(), **kw),
    )


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    path = tmp_path / "rules-secret.yaml"
    path.write_text(RULES, encoding="utf-8")
    return path


@pytest.fixture
def images(tmp_path: Path) -> Path:
    root = tmp_path / "images-secret"
    root.mkdir()
    for label, name in NAMES.items():
        make_image(label).save(root / name)
    return root


@pytest.fixture
def vision(vision_backend) -> NumericGate:
    models = load_config().models
    return NumericGate(vision_backend("graph", models.classifier, models.nsfw))


def write_labels(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "labels-secret.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def gate(images: Path, labels: Path, rules: Path, vision, *extra: str) -> int:
    return gate_3.main(
        list(extra), images=images, labels_path=labels, rules_path=rules, vision=vision
    )


def learn(tmp_path, images, rules, vision, monkeypatch) -> dict[str, tuple]:
    """Run once on placeholder labels and return what the node wrote, by file name."""
    seen: list = []
    real = gate_3.evaluate

    def spy(labels, outcomes, min_level):
        seen.extend(outcomes)
        return real(labels, outcomes, min_level)

    monkeypatch.setattr(gate_3, "evaluate", spy)
    probe = write_labels(tmp_path, [f"{n},,,no,,," for n in NAMES.values()])
    gate(images, probe, rules, vision)
    monkeypatch.setattr(gate_3, "evaluate", real)
    return {o.names[0]: (o.format, o.topic, o.branch, o.status) for o in seen}


def agreeing_rows(learned: dict[str, tuple]) -> list[str]:
    """Labels that agree with the node, one suggestive-negative among the safe rows."""
    rows = []
    tagged = False
    for name, (fmt, topic, branch, _status) in sorted(learned.items()):
        adult = "yes" if branch == "nsfw" else "no"
        topic = "" if topic == fmt else (topic or "")
        tag = ""
        if adult == "no" and not tagged:
            tag, tagged = "suggestive-negative", True
        rows.append(f"{name},{fmt or ''},{topic},{adult},,,{tag}")
    return rows


PUBLIC_LINES = 8


def test_the_node_flags_only_the_double_and_writes_formats(
    tmp_path, images, rules_path, vision, monkeypatch
) -> None:
    learned = learn(tmp_path, images, rules_path, vision, monkeypatch)
    assert set(learned) == set(NAMES.values())
    assert {n for n, v in learned.items() if v[2] == "nsfw"} == {FLAGGED}
    assert all(v[3] == "classified" for v in learned.values())


def test_a_run_on_agreeing_labels_prints_the_public_form(
    tmp_path, images, rules_path, vision, monkeypatch, capsys
) -> None:
    learned = learn(tmp_path, images, rules_path, vision, monkeypatch)
    capsys.readouterr()
    labels = write_labels(tmp_path, agreeing_rows(learned))
    code = gate(images, labels, rules_path, vision)
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert len(lines) == PUBLIC_LINES and out.err == ""
    assert lines[0].startswith("format agreement: 100% ") and lines[0].endswith(": ok")
    assert lines[3:7] == [
        "nsfw gate (adult flagged, safe not flagged): ok",
        "suggestive-negative rows safe: ok",
        "node errors: ok",
        "labels and images match: ok",
    ]
    assert lines[-1] == "gate 3 PASS" and code == 0


def test_a_missed_adult_label_fails_the_nsfw_line_without_a_digit(
    tmp_path, images, rules_path, vision, monkeypatch, capsys
) -> None:
    learned = learn(tmp_path, images, rules_path, vision, monkeypatch)
    capsys.readouterr()
    rows = [r.replace(",yes,", ",no,") for r in agreeing_rows(learned)]
    labels = write_labels(tmp_path, rows)
    assert gate(images, labels, rules_path, vision) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[3] == "nsfw gate (adult flagged, safe not flagged): FAIL"
    assert lines[-1] == "gate 3 FAIL"


def test_an_unlabelled_image_fails_coverage(
    tmp_path, images, rules_path, vision, monkeypatch, capsys
) -> None:
    learned = learn(tmp_path, images, rules_path, vision, monkeypatch)
    capsys.readouterr()
    labels = write_labels(tmp_path, agreeing_rows(learned)[:-1])
    assert gate(images, labels, rules_path, vision) == 1
    assert "labels and images match: FAIL" in capsys.readouterr().out


def test_a_label_outside_the_vocabulary_stops_with_a_line_and_a_column(
    tmp_path, images, rules_path, vision, capsys
) -> None:
    labels = write_labels(tmp_path, ["a-secret.png,notacategory,,no,,,"])
    assert gate(images, labels, rules_path, vision) == 1
    err = capsys.readouterr().err
    assert err.strip() == "gate 3 FAIL: labels line 2, column format: not in the format vocabulary"


def test_detail_stays_behind_the_flag(
    tmp_path, images, rules_path, vision, monkeypatch, capsys
) -> None:
    learned = learn(tmp_path, images, rules_path, vision, monkeypatch)
    capsys.readouterr()
    labels = write_labels(tmp_path, agreeing_rows(learned))
    gate(images, labels, rules_path, vision)
    plain = capsys.readouterr().out
    assert "DETAIL" not in plain
    gate(images, labels, rules_path, vision, "--detail")
    out = capsys.readouterr().out
    assert out.splitlines()[:PUBLIC_LINES] == plain.splitlines()
    assert "DETAIL" in out and "never paste" in out
    assert "secret" not in out
    assert not re.search(r"\d", plain.splitlines()[3] + plain.splitlines()[4])


def test_the_source_folder_is_left_alone(tmp_path, images, rules_path, vision, monkeypatch) -> None:
    learned = learn(tmp_path, images, rules_path, vision, monkeypatch)
    before = {p.name: p.read_bytes() for p in images.iterdir()}
    gate(images, write_labels(tmp_path, agreeing_rows(learned)), rules_path, vision)
    assert {p.name: p.read_bytes() for p in images.iterdir()} == before
