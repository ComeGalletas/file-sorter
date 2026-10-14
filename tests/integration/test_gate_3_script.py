"""TST-008.3.4: gate 3 end to end on synthetic images and labels (TST-008.D4, D6).

Ingest and sanitize are the real nodes, in a fresh migrated schema. Until the classify node
lands (CLS-002.2, #99) a stand-in node writes the ledger columns the real one will, from a table
the test controls; once #99 is on main the stand-in is replaced by the real node over replayed
vision (TST-008.1) and this docstring says so. Images are benign flat colours generated here, the
label vocabulary is read from the gate's own migrated schema, and no adult content exists: a
row's `adult` is a label column and a ledger `branch` is a string. The real fixtures only run at
`make gate-3` (TST-004).
"""

import importlib.util
import re
from pathlib import Path

import psycopg
import pytest
from PIL import Image

from classifier.graph.nodes import Node, NodeContext
from classifier.sanitize.rules import LOG_KEY_ENV
from tests.db.db_support import require_db_dsn

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "gate_3.py"
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


@pytest.fixture(autouse=True)
def log_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_KEY_ENV, "00112233445566778899aabbccddeeff")
    monkeypatch.setenv("DB_DSN", require_db_dsn())


@pytest.fixture
def rules_path(tmp_path: Path) -> Path:
    path = tmp_path / "rules-secret.yaml"
    path.write_text(RULES, encoding="utf-8")
    return path


@pytest.fixture
def images(tmp_path: Path) -> Path:
    root = tmp_path / "images-secret"
    root.mkdir()
    for index, name in enumerate(("a-secret.png", "b-secret.png", "c-secret.png")):
        Image.new("RGB", (8, 6), (10 * index + 5, 20, 30)).save(root / name)
    return root


def vocabulary() -> tuple[str, str, str, str]:
    """Two format names and two topic names from the committed categories, never hard-coded."""
    from tests.integration.schema_support import migrated_schema

    with migrated_schema(require_db_dsn()) as dsn:
        formats, topics = gate_3.read_vocabularies(dsn)
    fmts = sorted(formats - {"unsorted"})
    tops = sorted(topics - set(fmts[:2]))
    return fmts[0], fmts[1], tops[0], tops[1]


def labels_file(tmp_path: Path, rows: list[str]) -> Path:
    path = tmp_path / "labels-secret.csv"
    path.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def stand_in(table: dict[str, tuple[str, str | None, str]], status: str = "classified") -> Node:
    """The classify stand-in: format, topic and branch by file name (CLS-002.2 writes these)."""

    def run(conn: psycopg.Connection, ctx: NodeContext) -> None:
        for source_hash, path in conn.execute(
            "select source_hash, source_path from files where status = 'sanitized'"
        ).fetchall():
            fmt, topic, branch = table[Path(path).name]
            conn.execute(
                "update files set status = %s::file_status, format = %s, topic = %s, "
                "branch = %s where source_hash = %s",
                (status, fmt, topic, branch, source_hash),
            )

    return Node("classify", run)


def registry(classify: Node) -> list[Node]:
    from classifier.graph import nodes as graph_nodes

    return [*graph_nodes.REGISTRY, classify]


def gate(images: Path, labels: Path, rules: Path, classify: Node, *extra: str) -> int:
    return gate_3.main(
        list(extra),
        images=images,
        labels_path=labels,
        registry=registry(classify),
        rules_path=rules,
    )


def good_case(tmp_path: Path):
    f1, f2, t1, t2 = vocabulary()
    labels = labels_file(
        tmp_path,
        [
            f"a-secret.png,{f1},{t1},yes,,,",
            f"b-secret.png,{f2},{t2},no,,,suggestive-negative",
            f"c-secret.png,{f1},,no,,,",
        ],
    )
    table = {
        "a-secret.png": (f1, t1, "nsfw"),
        "b-secret.png": (f2, t2, "safe"),
        "c-secret.png": (f1, None, "safe"),
    }
    return labels, table


PUBLIC_PASS = (
    "format agreement: 100% (required >= 90%): ok",
    "topic agreement: 100% (required >= 85%): ok",
    "unrecognized format: 0% (required < 10%): ok",
    "nsfw gate (adult flagged, safe not flagged): ok",
    "suggestive-negative rows safe: ok",
    "node errors: ok",
    "labels and images match: ok",
    "gate 3 PASS",
)


def test_a_clean_run_prints_exactly_the_public_form(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    assert gate(images, labels, rules_path, stand_in(table)) == 0
    out = capsys.readouterr()
    assert tuple(out.out.splitlines()) == PUBLIC_PASS and out.err == ""


def test_a_missed_adult_row_fails_with_no_digit_on_the_line(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    table["a-secret.png"] = (*table["a-secret.png"][:2], "safe")
    assert gate(images, labels, rules_path, stand_in(table)) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[3] == "nsfw gate (adult flagged, safe not flagged): FAIL"
    assert lines[-1] == "gate 3 FAIL"


def test_a_flagged_suggestive_negative_row_fails_its_own_line(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    table["b-secret.png"] = (*table["b-secret.png"][:2], "nsfw")
    assert gate(images, labels, rules_path, stand_in(table)) == 1
    lines = capsys.readouterr().out.splitlines()
    assert lines[4] == "suggestive-negative rows safe: FAIL"
    assert not re.search(r"\d", lines[3] + lines[4])


def test_an_unlabelled_image_fails_coverage(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    Image.new("RGB", (8, 6), (200, 20, 30)).save(images / "d-secret.png")
    table["d-secret.png"] = table["c-secret.png"]
    assert gate(images, labels, rules_path, stand_in(table)) == 1
    assert "labels and images match: FAIL" in capsys.readouterr().out


def test_a_node_error_fails(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    assert gate(images, labels, rules_path, stand_in(table, status="error")) == 1
    assert "node errors: FAIL" in capsys.readouterr().out


def test_a_label_outside_the_vocabulary_stops_with_a_line_and_a_column(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    labels.write_text(HEADER + "a-secret.png,notacategory,,no,,,\n", encoding="utf-8")
    assert gate(images, labels, rules_path, stand_in(table)) == 1
    err = capsys.readouterr().err
    assert err.strip() == "gate 3 FAIL: labels line 2, column format: not in the format vocabulary"


def test_detail_stays_behind_the_flag(
    tmp_path: Path, images: Path, rules_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    labels, table = good_case(tmp_path)
    assert gate(images, labels, rules_path, stand_in(table)) == 0
    assert "DETAIL" not in capsys.readouterr().out
    assert gate(images, labels, rules_path, stand_in(table), "--detail") == 0
    out = capsys.readouterr().out
    assert tuple(out.splitlines()[: len(PUBLIC_PASS)]) == PUBLIC_PASS
    assert "DETAIL" in out and "never paste" in out
    assert "secret" not in out  # no file name even in the detail


def test_nothing_is_left_in_the_results_tree_or_the_default_schema(
    tmp_path: Path, images: Path, rules_path: Path
) -> None:
    labels, table = good_case(tmp_path)
    before = sorted(p.name for p in tmp_path.iterdir())
    assert gate(images, labels, rules_path, stand_in(table)) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == before
    assert sorted(p.name for p in images.iterdir()) == [
        "a-secret.png",
        "b-secret.png",
        "c-secret.png",
    ]
