"""TST-008.3.1, .2: gate 3's measures and its public-form output (TST-008.D1, D4, D6).

Synthetic labels and synthetic ledger rows only, with artificial coinages for every name and
category. No db, no images, and never the real fixtures (TST-004). No adult content is described
or built: `adult` is a plain label column here.
"""

import importlib.util
import re
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_3.py"
_spec = importlib.util.spec_from_file_location("gate_3", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_3)

HEADER = "file,format,topic,adult,reference,subject,tags\n"
FORMATS = {"zorbs", "qwims", "unsorted"}
TOPICS = {"plinth", "vexil"}


def labels(rows: list[str]):
    return gate_3.fixture_labels.parse_labels(
        HEADER + "\n".join(rows) + "\n", formats=FORMATS, topics=TOPICS
    )


def out(name, fmt="zorbs", topic="plinth", branch="safe", status="classified"):
    return gate_3.Outcome(names=(name,), status=status, format=fmt, topic=topic, branch=branch)


def good_set(n: int):
    """n rows, all matched: zorbs/plinth, safe."""
    rows = [f"zz{i}.png,zorbs,plinth,no,,," for i in range(n)]
    return labels(rows), [out(f"zz{i}.png") for i in range(n)]


def measures(lset, outcomes):
    return gate_3.evaluate(lset, outcomes)


def test_all_matched_passes() -> None:
    lset, outs = good_set(10)
    verdict = gate_3.judge(measures(lset, outs))
    assert verdict.passed is False  # no adult and no suggestive-negative row: unmeasured
    rows = [
        "a.png,zorbs,plinth,yes,,,",
        "b.png,zorbs,plinth,no,,,suggestive-negative",
        "c.png,zorbs,plinth,no,,,",
    ]
    outs = [out("a.png", branch="nsfw"), out("b.png"), out("c.png")]
    verdict = gate_3.judge(measures(labels(rows), outs))
    assert verdict.passed
    assert verdict.lines[-1] == "gate 3 PASS"


def _pass_rows(extra_rows: list[str], extra_outs: list):
    rows = [
        "a.png,zorbs,plinth,yes,,,",
        "b.png,zorbs,plinth,no,,,suggestive-negative",
        *extra_rows,
    ]
    return labels(rows), [out("a.png", branch="nsfw"), out("b.png"), *extra_outs]


@pytest.mark.parametrize(
    ("hit", "total", "verdict_ok", "printed"),
    [(8999, 10000, False, 89), (9000, 10000, True, 90), (9, 10, True, 90), (89, 100, False, 89)],
)
def test_format_boundary_uses_exact_ratio_and_prints_floor(hit, total, verdict_ok, printed) -> None:
    tally = gate_3.Tally(hit, total)
    assert tally.at_least(90) is verdict_ok
    assert tally.floor_pct() == printed


def test_format_boundary_line_89_99_fails_prints_89_and_90_0_passes_prints_90() -> None:
    base = dict(
        topic=gate_3.Tally(100, 100),
        unrecognized=gate_3.Tally(0, 100),
        adult=gate_3.Tally(1, 1),
        safe=gate_3.Tally(1, 1),
        suggestive=gate_3.Tally(1, 1),
        errors=0,
        coverage_ok=True,
        by_format=(),
        by_topic=(),
    )
    low = gate_3.judge(gate_3.Measures(format=gate_3.Tally(8999, 10000), **base))
    high = gate_3.judge(gate_3.Measures(format=gate_3.Tally(9000, 10000), **base))
    assert low.lines[0] == "format agreement: 89% (required >= 90%): FAIL" and not low.passed
    assert high.lines[0] == "format agreement: 90% (required >= 90%): ok" and high.passed


def test_topic_boundary_is_85_inclusive() -> None:
    assert gate_3.Tally(85, 100).at_least(85)
    assert not gate_3.Tally(84999, 100000).at_least(85)
    assert gate_3.Tally(84999, 100000).floor_pct() == 84


def test_unrecognized_is_strictly_below_10() -> None:
    assert gate_3.Tally(99, 1000).below(10)
    assert not gate_3.Tally(100, 1000).below(10)  # exactly 10% fails
    assert gate_3.Tally(100, 1000).floor_pct() == 10


def test_empty_tallies_are_unmeasured_and_fail() -> None:
    empty = gate_3.Tally(0, 0)
    assert not empty.at_least(0) and not empty.below(10) and not gate_3._all_hit(empty)
    assert empty.floor_pct() == 0


def test_blank_labels_are_not_scored() -> None:
    lset, outs = _pass_rows(
        ["c.png,,,no,,,", "d.png,zorbs,,no,,,"],
        [out("c.png", fmt="qwims", topic=None), out("d.png", topic="vexil")],
    )
    m = measures(lset, outs)
    assert (m.format.hit, m.format.total) == (3, 3)  # c has no format label
    assert (m.topic.hit, m.topic.total) == (2, 2)  # c and d have no topic label


def test_unsorted_and_missing_topic_are_misses() -> None:
    lset, outs = _pass_rows(
        ["c.png,zorbs,plinth,no,,,"], [out("c.png", fmt="unsorted", topic=None)]
    )
    m = measures(lset, outs)
    assert m.format.hit == 2 and m.format.total == 3
    assert m.topic.hit == 2 and m.topic.total == 3
    assert (m.unrecognized.hit, m.unrecognized.total) == (1, 3)


def test_calibration_only_rows_count_nowhere() -> None:
    lset, outs = _pass_rows(
        ["c.png,qwims,vexil,yes,,,calibration-only"],
        [out("c.png", fmt="unsorted", topic=None, branch="safe")],
    )
    m = measures(lset, outs)
    assert m.format.total == 2 and m.topic.total == 2
    assert m.unrecognized.total == 2 and m.unrecognized.hit == 0
    assert m.adult.total == 1 and m.safe.total == 1
    assert m.coverage_ok  # a calibration-only image still has to be matched
    assert gate_3.judge(m).passed


def test_adult_must_be_nsfw_and_safe_must_be_safe() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [out("c.png", branch="nsfw")])
    verdict = gate_3.judge(measures(lset, outs))
    assert not verdict.passed
    assert verdict.lines[3].endswith(": FAIL")
    lset, outs = _pass_rows([], [])
    outs[0] = out("a.png", branch="safe")  # the adult row missed
    assert gate_3.judge(measures(lset, outs)).lines[3].endswith(": FAIL")


def test_suggestive_negative_flagged_fails_its_own_line() -> None:
    lset, outs = _pass_rows([], [])
    outs[1] = out("b.png", branch="nsfw")
    verdict = gate_3.judge(measures(lset, outs))
    assert verdict.lines[4] == "suggestive-negative rows safe: FAIL"
    assert not verdict.passed


def test_any_error_row_fails() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [out("c.png", status="error")])
    verdict = gate_3.judge(measures(lset, outs))
    assert verdict.lines[5] == "node errors: FAIL" and not verdict.passed


def test_error_row_without_a_label_still_fails() -> None:
    lset, outs = _pass_rows([], [out("zz.png", status="error")])
    m = measures(lset, outs)
    assert m.errors == 1 and not m.coverage_ok


def test_coverage_label_without_image_fails() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [])
    assert not measures(lset, outs).coverage_ok


def test_coverage_image_without_label_fails_but_skipped_is_exempt() -> None:
    lset, outs = _pass_rows([], [out("c.png")])
    assert not measures(lset, outs).coverage_ok
    lset, outs = _pass_rows([], [out("c.png", status="skipped", fmt=None, topic=None, branch=None)])
    assert measures(lset, outs).coverage_ok


def test_duplicate_path_matches_its_label_and_two_rows_on_one_name_fail() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [])
    dup = gate_3.Outcome(("x.png", "c.png"), "classified", "zorbs", "plinth", "safe")
    assert measures(lset, [*outs, dup]).coverage_ok  # c.png labels the row; x.png rides along
    assert not measures(lset, [*outs, dup, out("c.png")]).coverage_ok  # one name, two rows


def test_unrecognized_failure_in_output() -> None:
    rows = [f"u{i}.png,zorbs,plinth,no,,," for i in range(10)]
    rows += ["a.png,zorbs,plinth,yes,,,", "b.png,zorbs,plinth,no,,,suggestive-negative"]
    outs = [out(f"u{i}.png", fmt="unsorted" if i == 0 else "zorbs") for i in range(10)]
    outs += [out("a.png", branch="nsfw"), out("b.png")]
    verdict = gate_3.judge(measures(labels(rows), outs))
    assert verdict.lines[2] == "unrecognized format: 8% (required < 10%): ok"
    outs[1] = out("u1.png", fmt="unsorted")
    verdict = gate_3.judge(measures(labels(rows), outs))
    assert verdict.lines[2] == "unrecognized format: 16% (required < 10%): FAIL"


# --- The public form (TST-008.D1, D6) ----------------------------------------------------


def test_default_output_is_exactly_the_public_form() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [out("c.png")])
    verdict = gate_3.judge(measures(lset, outs))
    assert verdict.lines == (
        "format agreement: 100% (required >= 90%): ok",
        "topic agreement: 100% (required >= 85%): ok",
        "unrecognized format: 0% (required < 10%): ok",
        "nsfw gate (adult flagged, safe not flagged): ok",
        "suggestive-negative rows safe: ok",
        "node errors: ok",
        "labels and images match: ok",
        "gate 3 PASS",
    )
    assert verdict.detail == ()


def test_adult_and_suggestive_lines_carry_no_digit_pass_or_fail() -> None:
    lset, outs = _pass_rows([], [])
    for branch_a, branch_b in (("nsfw", "safe"), ("safe", "nsfw")):
        outs[0] = out("a.png", branch=branch_a)
        outs[1] = out("b.png", branch=branch_b)
        lines = gate_3.judge(measures(lset, outs)).lines
        for line in (lines[3], lines[4]):
            assert not re.search(r"\d", line)


def test_default_output_has_no_count_or_label_value() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [out("c.png")])
    text = "\n".join(gate_3.judge(measures(lset, outs)).lines)
    for forbidden in ("zorbs", "plinth", "vexil", "a.png", "/"):
        assert forbidden not in text
    assert re.findall(r"\d+", text) == ["100", "90", "100", "85", "0", "10", "3"]


def test_detail_adds_lines_and_marks_them_box_only() -> None:
    lset, outs = _pass_rows(["c.png,zorbs,plinth,no,,,"], [out("c.png")])
    plain = gate_3.judge(measures(lset, outs))
    detailed = gate_3.judge(measures(lset, outs), detail=True)
    assert detailed.lines == plain.lines
    assert "never paste" in detailed.detail[0]
    assert any("zorbs" in line for line in detailed.detail)


def test_detail_prints_one_decimal_floor() -> None:
    assert gate_3.Tally(2, 3).floor_tenths() == "66.6"
    assert gate_3.Tally(8999, 10000).floor_tenths() == "89.9"
    assert gate_3.Tally(0, 0).floor_tenths() == "0.0"


# --- repr hygiene (privacy checklist 4) ----------------------------------------------------

PLANTED = "Qzxv-Planted-Secret"


def test_repr_and_str_hold_no_planted_value() -> None:
    row = gate_3.Outcome(
        names=(PLANTED,), status=PLANTED, format=PLANTED, topic=PLANTED, branch=PLANTED
    )
    lset = labels([f"{PLANTED}.png,zorbs,plinth,no,,,"])
    m = gate_3.evaluate(lset, [row])
    for obj in (row, m, m.format, gate_3.judge(m), gate_3.judge(m, detail=False)):
        assert PLANTED not in repr(obj) and PLANTED not in str(obj)
    assert repr(m.format) == "Tally()"
    assert not any(PLANTED in line for line in gate_3.judge(m).lines)
