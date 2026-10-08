"""TST-005.2.3: gate 2's run, prerequisites and error paths, on synthetic data only.

A planted-secret rules file stands in for the human's sanitize.yaml, and a fake detector that
knows eval/data/entity_synthetic.yaml stands in for Ollama. The real fixtures only run at
`make gate-2`. The end-to-end PASS through the sanitize node comes with TST-005.2.4 (#56).
"""

import importlib.util
import re
import subprocess
import sys
import traceback
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from classifier.sanitize import exif
from classifier.sanitize.entity import EntityUnavailableError
from classifier.sanitize.rules import LOG_KEY_ENV
from tests.db.db_support import require_db_dsn

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gate_2.py"
spec = importlib.util.spec_from_file_location("gate_2", SCRIPT)
assert spec and spec.loader
gate_2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_2)

SECRET = "Zyxwq Plonk"  # stands in for the human's literal value
SECRET_WORDS = ("zyxwq", "plonk")

RULES = f"""
exif:
  mode: strip_all
  keep: [Orientation, DateTimeOriginal]
rules:
  - id: mine
    type: literal
    values: ["{SECRET}", "Qwvzz Secretname"]
    replace: "[PERSON]"
  - id: email
    type: regex
    pattern: "[\\\\w.+-]+@[\\\\w-]+\\\\.[\\\\w.]+"
    replace: "[EMAIL]"
  - id: phone
    type: regex
    pattern: "\\\\+?\\\\d[\\\\d\\\\s().-]{{7,}}\\\\d"
    replace: "[PHONE]"
  - id: entities
    type: entity
    labels: [PERSON, ORG, LOCATION]
    replace: "[{{label}}]"
"""

NODE_RULES = f"""
exif:
  mode: strip_all
  keep: [Orientation, DateTimeOriginal]
rules:
  - {{id: mine, type: literal, values: ["{SECRET}"], replace: "[PERSON]"}}
"""

NO_LITERAL = """
exif: {mode: strip_all}
rules:
  - {id: email, type: regex, pattern: "@", replace: "[EMAIL]"}
"""


def leaked(text: str) -> bool:
    return any(word in text.lower() for word in (*SECRET_WORDS, "qwvzz", "secretname"))


@pytest.fixture(autouse=True)
def log_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_KEY_ENV, "00112233445566778899aabbccddeeff")


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    path = tmp_path / "rules-secret.yaml"
    path.write_text(RULES, encoding="utf-8")
    return path


@pytest.fixture
def images(tmp_path: Path) -> Path:
    root = tmp_path / "images-secret"
    root.mkdir()
    Image.new("RGB", (8, 6), (10, 20, 30)).save(root / "a-secret.png")
    return root


def perfect_detector() -> object:
    """Finds every fictional name of entity_synthetic.yaml, in any of its spellings."""
    names = gate_2.load_entity_names(gate_2.ENTITY_DATA)
    gap = "[ _.\\-]?"

    def alternatives(values: Sequence[str]) -> str:
        return "|".join(gap.join(map(re.escape, v.split())) for v in values)

    people = f"(?:{alternatives(names.first)}){gap}(?:{alternatives(names.last)})"
    patterns = [
        (re.compile(people), "PERSON"),
        (re.compile(alternatives(names.orgs)), "ORG"),
        (re.compile(alternatives(names.places)), "LOCATION"),
    ]

    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [
            (match[0], label)
            for pattern, label in patterns
            if label in labels
            for match in pattern.finditer(text)
        ]

    return entity


def output(capsys: pytest.CaptureFixture[str]) -> str:
    out = capsys.readouterr()
    return out.out + out.err


# --- the names half, through the real rules loader and sanitize_name ----------------------


def test_the_names_half_passes_on_complete_rules(rules_path: Path) -> None:
    rules = gate_2.load_local_rules(rules_path)
    names = gate_2.load_entity_names(gate_2.ENTITY_DATA)
    assert gate_2.measure_names(rules, names, perfect_detector()) == (
        True,
        "names: residual seeded values 0.0% (required 0.0%): ok",
    )


def test_a_detector_that_misses_people_fails_the_names_half(rules_path: Path) -> None:
    rules = gate_2.load_local_rules(rules_path)
    names = gate_2.load_entity_names(gate_2.ENTITY_DATA)
    full = perfect_detector()

    def no_people(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [pair for pair in full(text, labels) if pair[1] != "PERSON"]  # type: ignore[operator]

    ok, line = gate_2.measure_names(rules, names, no_people)
    assert not ok and line == "names: residual seeded values 20.0% (required 0.0%): FAIL"


def test_an_entity_failure_mid_run_is_fixed_text_and_unchained(rules_path: Path) -> None:
    rules = gate_2.load_local_rules(rules_path)
    names = gate_2.load_entity_names(gate_2.ENTITY_DATA)
    calls = []

    def flaky(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        calls.append(text)
        if len(calls) > 3:
            raise EntityUnavailableError()
        return []

    with pytest.raises(gate_2.GateRunError) as caught:
        gate_2.measure_names(rules, names, flaky)
    error = caught.value
    assert error.__cause__ is None and error.__context__ is None
    shown = "".join(traceback.format_exception(error)) + repr(error)
    assert "sanitize_entity_unavailable" in shown and not leaked(shown)


# --- the metadata half, through the real ingest node and db -------------------------------


def test_without_the_sanitize_node_nothing_is_sanitized(tmp_path: Path, rules_path: Path) -> None:
    """Ingest alone leaves every input queued: the gate fails it (TST-005.D7)."""
    from classifier.graph import nodes as graph_nodes

    folder = tmp_path / "synthetic"
    folder.mkdir()
    markers = gate_2.make_seeded_images(folder)
    ingest = tuple(n for n in graph_nodes.REGISTRY if n.name == "ingest")
    judged = gate_2.measure_metadata(
        require_db_dsn(),
        folder,
        "synthetic",
        gate_2.load_local_rules(rules_path),
        rules_path,
        lambda tag: False,
        ingest,
        markers,
    )
    assert judged == [
        (
            False,
            "metadata, synthetic: 0.0% sanitized, 0.0% of outputs clean "
            "(required 100.0% and 100.0%): FAIL",
        ),
        (True, "metadata, synthetic: seeded values in results files: ok"),
    ]
    assert sorted(p.name for p in folder.iterdir()) == sorted(
        f"synthetic_{i:02d}.{ext}" for i, (ext, _, _) in enumerate(gate_2.SYNTHETIC_FORMATS)
    )  # the source set is untouched


def test_the_metadata_half_passes_through_the_real_sanitize_node(tmp_path: Path) -> None:
    """TST-005.2.4: ingest and #56's node on the seeded set, judged with the public
    is_structure_tag. No entity rule here, so the node never calls Ollama (CLAUDE.md §3)."""
    from classifier.graph import nodes as graph_nodes

    path = tmp_path / "node-rules.yaml"
    path.write_text(NODE_RULES, encoding="utf-8")
    folder = tmp_path / "synthetic"
    folder.mkdir()
    markers = gate_2.make_seeded_images(folder)
    judged = gate_2.measure_metadata(
        require_db_dsn(),
        folder,
        "synthetic",
        gate_2.load_local_rules(path),
        path,
        gate_2.structure_predicate(),
        gate_2.gate_nodes(graph_nodes.REGISTRY),
        markers,
    )
    assert judged == [
        (
            True,
            "metadata, synthetic: 100.0% sanitized, 100.0% of outputs clean "
            "(required 100.0% and 100.0%): ok",
        ),
        (True, "metadata, synthetic: seeded values in results files: ok"),
    ]


def test_the_registry_holds_the_gate_nodes_and_the_public_predicate() -> None:
    from classifier.graph import nodes as graph_nodes

    assert [n.name for n in gate_2.gate_nodes(graph_nodes.REGISTRY)] == ["ingest", "sanitize"]
    assert gate_2.structure_predicate() is exif.is_structure_tag


def test_a_working_copy_is_judged_by_tags_and_markers(tmp_path: Path, rules_path: Path) -> None:
    rules = gate_2.load_local_rules(rules_path)
    folder = tmp_path / "set"
    folder.mkdir()
    markers = gate_2.make_seeded_images(folder)
    work = tmp_path / ".work"
    work.mkdir()
    (work / "abc.jpg").write_bytes((folder / "synthetic_00.jpg").read_bytes())
    everything = lambda tag: True  # noqa: E731
    assert not gate_2._clean_output(work, "abc", rules, everything, markers)  # markers
    assert gate_2._clean_output(work, "abc", rules, everything, ())
    assert not gate_2._clean_output(work, "abc", rules, lambda tag: False, ())  # tags
    assert not gate_2._clean_output(work, "missing", rules, everything, ())
    (work / "abc.png").write_bytes(b"")
    assert not gate_2._clean_output(work, "abc", rules, everything, ())  # two copies


# --- prerequisites: each fails naming what is missing, never skips ------------------------


def test_the_script_reaches_the_app_from_a_clean_interpreter(tmp_path: Path) -> None:
    """Regression: `python scripts/gate_2.py` failed with ModuleNotFoundError, because only
    scripts/ was on sys.path. -I drops PYTHONPATH; the cwd is outside the repo."""
    code = (
        "import importlib.util as u\n"
        f"s = u.spec_from_file_location('gate_2', {str(SCRIPT)!r})\n"
        "m = u.module_from_spec(s)\n"
        "s.loader.exec_module(m)\n"
        "import classifier.config, classifier.graph.run, tests.integration.schema_support\n"
    )
    done = subprocess.run(
        [sys.executable, "-I", "-c", code], cwd=tmp_path, capture_output=True, check=False
    )
    assert done.returncode == 0, done.stderr.decode(errors="replace")[-300:]


def test_the_node_pair_is_picked_in_order() -> None:
    reg = [SimpleNamespace(name=n) for n in ("ingest", "sanitize", "classify")]
    assert [n.name for n in gate_2.gate_nodes(reg)] == ["ingest", "sanitize"]
    for broken in (reg[:1], [reg[0], reg[1], reg[1]], reg[1:]):
        with pytest.raises(gate_2.GateSetupError, match="#56"):
            gate_2.gate_nodes(broken)


def test_the_structure_predicate_is_only_ever_the_public_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(exif, "is_structure_tag", raising=False)
    with pytest.raises(gate_2.GateSetupError, match="is_structure_tag"):
        gate_2.structure_predicate()

    def public(tag: object) -> bool:
        return True

    monkeypatch.setattr(exif, "is_structure_tag", public, raising=False)
    assert gate_2.structure_predicate() is public


def run_main(images: Path, rules_path: Path, **over: object) -> int:
    args: dict[str, object] = {
        "rules_path": rules_path,
        "entity": perfect_detector(),
        "is_structure": lambda tag: True,
    }
    return gate_2.main(images, **{**args, **over})  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("no_dsn", "DB_DSN is not set"),
        ("no_images", "is missing or empty: gate 2 sanitizes the human's real"),
        ("no_entity_data", "entity_synthetic.yaml is missing"),
        ("no_rules", "sanitize.yaml is missing or invalid"),
        ("bad_rules", "sanitize.yaml is missing or invalid"),
        ("no_literal", "sanitize.yaml has no `literal` rule"),
        ("no_key", f"{LOG_KEY_ENV} is not set"),
        ("no_ollama", "can't reach Ollama or models.text_llm"),
    ],
)
def test_a_missing_prerequisite_fails_naming_it(
    setup: str,
    expected: str,
    tmp_path: Path,
    images: Path,
    rules_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("DB_DSN", require_db_dsn())
    over: dict[str, object] = {}
    if setup == "no_dsn":
        monkeypatch.delenv("DB_DSN")
    elif setup == "no_images":
        images = tmp_path / "absent"
    elif setup == "no_entity_data":
        over["entity_data"] = tmp_path / "absent.yaml"
    elif setup == "no_rules":
        rules_path = tmp_path / "absent-secret.yaml"
    elif setup == "bad_rules":
        rules_path.write_text(RULES.replace("type: literal", "type: literally"), "utf-8")
    elif setup == "no_literal":
        rules_path.write_text(NO_LITERAL, "utf-8")
    elif setup == "no_key":
        monkeypatch.delenv(LOG_KEY_ENV)
    elif setup == "no_ollama":

        def down(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
            raise EntityUnavailableError()

        over["entity"] = down
    assert run_main(images, rules_path, **over) == 1
    text = output(capsys)
    assert text.startswith("gate 2 FAIL: ") and expected in text
    assert "PASS" not in text and not leaked(text) and str(tmp_path) not in text


def test_an_unexpected_error_prints_only_its_type(
    images: Path,
    rules_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def boom(*args: object) -> None:
        raise RuntimeError(f"{SECRET} {args}")

    monkeypatch.setenv("DB_DSN", "postgresql://user:pw@host/db")
    monkeypatch.setattr(gate_2, "measure", boom)
    assert run_main(images, rules_path) == 1
    text = output(capsys)
    assert text == "gate 2 FAIL: run errored (RuntimeError)\n"


def test_main_prints_the_lines_and_the_verdict(
    images: Path,
    rules_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    passed = gate_2.verdict((True, "names: ok line"), (True, "metadata: ok line"))
    monkeypatch.setenv("DB_DSN", require_db_dsn())
    monkeypatch.setattr(gate_2, "measure", lambda *args: passed)
    assert run_main(images, rules_path) == 0
    assert output(capsys) == f"names: ok line\nmetadata: ok line\ngate 2 PASS: {gate_2.CRITERION}\n"

    failed = gate_2.verdict((True, "names: ok line"), (False, "metadata: FAIL line"))
    monkeypatch.setattr(gate_2, "measure", lambda *args: failed)
    assert run_main(images, rules_path) == 1
    assert output(capsys).endswith(f"gate 2 FAIL: {gate_2.CRITERION}\n")
