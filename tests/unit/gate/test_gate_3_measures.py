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


MIN_LEVEL = 2  # nsfw.min_level = nudity (CLS-004.D3)
_DEFAULT_LEVEL = {"nsfw": "nudity", "safe": "safe", None: None}


def out(name, fmt="zorbs", topic="plinth", branch="safe", status="classified", level="auto"):
    """A ledger row as the VLM node writes it: the level follows the branch unless given."""
    if level == "auto":
        level = _DEFAULT_LEVEL[branch]
    return gate_3.Outcome(
        names=(name,), status=status, format=fmt, topic=topic, branch=branch, nsfw_level=level
    )


def good_set(n: int):
    """n rows, all matched: zorbs/plinth, safe."""
    rows = [f"zz{i}.png,zorbs,plinth,no,,," for i in range(n)]
    return labels(rows), [out(f"zz{i}.png") for i in range(n)]


def measures(lset, outcomes):
    return gate_3.evaluate(lset, outcomes, MIN_LEVEL)


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
    [(8499, 10000, False, 84), (8500, 10000, True, 85), (17, 20, True, 85), (84, 100, False, 84)],
)
def test_format_boundary_uses_exact_ratio_and_prints_floor(hit, total, verdict_ok, printed) -> None:
    tally = gate_3.Tally(hit, total)
    assert tally.at_least(85) is verdict_ok
    assert tally.floor_pct() == printed


def test_format_boundary_line_84_99_fails_prints_84_and_85_0_passes_prints_85() -> None:
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
    low = gate_3.judge(gate_3.Measures(format=gate_3.Tally(8499, 10000), **base))
    high = gate_3.judge(gate_3.Measures(format=gate_3.Tally(8500, 10000), **base))
    assert low.lines[0] == "format agreement: 84% (required >= 85%): FAIL" and not low.passed
    assert high.lines[0] == "format agreement: 85% (required >= 85%): ok" and high.passed


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
        "format agreement: 100% (required >= 85%): ok",
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
    assert re.findall(r"\d+", text) == ["100", "85", "100", "85", "0", "10", "3"]


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
        names=(PLANTED,),
        status=PLANTED,
        format=PLANTED,
        topic=PLANTED,
        branch=PLANTED,
        nsfw_level=PLANTED,
    )
    lset = labels([f"{PLANTED}.png,zorbs,plinth,no,,,"])
    m = gate_3.evaluate(lset, [row], MIN_LEVEL)
    for obj in (row, m, m.format, gate_3.judge(m), gate_3.judge(m, detail=False)):
        assert PLANTED not in repr(obj) and PLANTED not in str(obj)
    assert repr(m.format) == "Tally()"
    assert not any(PLANTED in line for line in gate_3.judge(m).lines)


def test_a_detailed_verdict_hides_its_label_names_from_repr_and_str() -> None:
    """TST-008.3.7: `detail` holds per-category names and counts; a repr must not show them."""
    planted_topic = PLANTED + "-topic"
    lset = gate_3.fixture_labels.parse_labels(
        HEADER + f"x.png,{PLANTED},{planted_topic},no,,,\n",
        formats={PLANTED},
        topics={planted_topic},
    )
    outs = [gate_3.Outcome(("x.png",), "classified", PLANTED, planted_topic, "safe")]
    m = gate_3.evaluate(lset, outs, MIN_LEVEL)
    verdict = gate_3.judge(m, detail=True)
    assert any(PLANTED in line for line in verdict.detail)  # the detail really holds the names
    for text in (repr(verdict), str(verdict), repr(m), str(m)):
        assert PLANTED not in text and planted_topic not in text
    assert repr(verdict) == "Verdict(passed=False)"


# --- TST-009.2.3: NSFW judged by level at min_level (TST-009.D1) ----------------------------

LEVEL_HEADER = "file,format,topic,adult,reference,subject,tags,nsfw_level\n"
LEVELS = ("safe", "suggestive", "nudity", "explicit")


def level_labels(rows: list[str]):
    return gate_3.fixture_labels.parse_labels(
        LEVEL_HEADER + "\n".join(rows) + "\n", formats=FORMATS, topics=TOPICS
    )


def nsfw_line(lset, outs, min_level=MIN_LEVEL) -> str:
    return gate_3.judge(gate_3.evaluate(lset, outs, min_level)).lines[3]


@pytest.mark.parametrize("min_level", [1, 2, 3])
@pytest.mark.parametrize("level", LEVELS)
def test_a_row_is_adult_exactly_from_min_level_up(level, min_level) -> None:
    """The label says `no`; the level alone decides. The ledger agrees when its branch follows
    the level, and the row is a hit on either side of the boundary."""
    adult = LEVELS.index(level) >= min_level
    lset = level_labels([f"a.png,zorbs,plinth,no,,,,{level}"])
    outs = [out("a.png", branch="nsfw" if adult else "safe", level=level)]
    m = gate_3.evaluate(lset, outs, min_level)
    side = m.adult if adult else m.safe
    assert (side.hit, side.total) == (1, 1)
    other = m.safe if adult else m.adult
    assert other.total == 0


def test_a_label_level_overrides_the_adult_column_and_none_falls_back() -> None:
    lset = level_labels(
        [
            "a.png,zorbs,plinth,no,,,,explicit",  # level says adult, column says no
            "b.png,zorbs,plinth,yes,,,,suggestive",  # level says safe, column says yes
            "c.png,zorbs,plinth,yes,,,,",  # no level: the column stands
            "d.png,zorbs,plinth,no,,,,",
        ]
    )
    outs = [
        out("a.png", branch="nsfw", level="explicit"),
        out("b.png", branch="safe", level="suggestive"),
        out("c.png", branch="nsfw", level="nudity"),
        out("d.png"),
    ]
    m = gate_3.evaluate(lset, outs, MIN_LEVEL)
    assert (m.adult.hit, m.adult.total) == (2, 2)
    assert (m.safe.hit, m.safe.total) == (2, 2)


def test_branch_and_level_must_agree() -> None:
    lset = level_labels(["a.png,zorbs,plinth,no,,,,explicit", "b.png,zorbs,plinth,no,,,,safe"])
    good = [out("a.png", branch="nsfw", level="explicit"), out("b.png")]
    assert nsfw_line(lset, good).endswith(": ok")
    # an adult-level row kept in the safe branch, and a safe-level row sent to nsfw
    assert nsfw_line(lset, [out("a.png", branch="safe", level="explicit"), good[1]]).endswith(
        "FAIL"
    )
    assert nsfw_line(lset, [good[0], out("b.png", branch="nsfw", level="safe")]).endswith("FAIL")


@pytest.mark.parametrize("level", [None, "qorvex-level", ""])
def test_a_missing_or_unknown_ledger_level_is_a_miss_on_either_side(level) -> None:
    lset = level_labels(["a.png,zorbs,plinth,no,,,,explicit", "b.png,zorbs,plinth,no,,,,safe"])
    outs = [out("a.png", branch="nsfw", level="explicit"), out("b.png", level=level)]
    assert nsfw_line(lset, outs).endswith("FAIL")
    outs = [out("a.png", branch="nsfw", level=level), out("b.png")]
    assert nsfw_line(lset, outs).endswith("FAIL")


def test_a_suggestive_negative_is_hit_only_by_a_safe_branch_below_min_level() -> None:
    lset = level_labels(
        [
            "a.png,zorbs,plinth,yes,,,,explicit",
            "b.png,zorbs,plinth,no,,suggestive-negative,suggestive-negative,suggestive",
        ]
    )
    good = [out("a.png", branch="nsfw", level="explicit"), out("b.png", level="suggestive")]
    m = gate_3.evaluate(lset, good, MIN_LEVEL)
    assert (m.suggestive.hit, m.suggestive.total) == (1, 1)
    assert gate_3.judge(m).passed
    for bad in (out("b.png", branch="nsfw", level="suggestive"), out("b.png", level="nudity")):
        m = gate_3.evaluate(lset, [good[0], bad], MIN_LEVEL)
        assert m.suggestive.hit == 0
        assert gate_3.judge(m).lines[4] == "suggestive-negative rows safe: FAIL"


def test_a_suggestive_negative_at_min_level_is_a_labels_error() -> None:
    lset = level_labels(["a.png,zorbs,plinth,no,,,suggestive-negative,nudity"])
    with pytest.raises(gate_3.fixture_labels.LabelsError) as info:
        gate_3.evaluate(lset, [out("a.png", level="nudity")], MIN_LEVEL)
    assert str(info.value) == (
        "labels line 2, column nsfw_level: suggestive-negative cannot be adult"
    )
    assert info.value.__cause__ is None and info.value.__context__ is None
    # the same row is fine when min_level sits above its level
    assert gate_3.evaluate(lset, [out("a.png", level="nudity")], 3).suggestive.total == 1


def test_a_calibration_only_row_is_not_checked_for_the_contradiction() -> None:
    lset = level_labels(
        [
            "a.png,zorbs,plinth,yes,,,,explicit",
            "b.png,zorbs,plinth,no,,,suggestive-negative,suggestive",
            "c.png,zorbs,plinth,no,,,suggestive-negative;calibration-only,explicit",
        ]
    )
    outs = [
        out("a.png", branch="nsfw", level="explicit"),
        out("b.png", level="suggestive"),
        out("c.png"),
    ]
    assert gate_3.evaluate(lset, outs, MIN_LEVEL).suggestive.total == 1


def test_the_level_gate_keeps_the_public_form() -> None:
    lset = level_labels(
        [
            "a.png,zorbs,plinth,no,,,,explicit",
            "b.png,zorbs,plinth,no,,,suggestive-negative,suggestive",
        ]
    )
    outs = [out("a.png", branch="nsfw", level="explicit"), out("b.png", level="suggestive")]
    verdict = gate_3.judge(gate_3.evaluate(lset, outs, MIN_LEVEL))
    assert verdict.passed
    text = "\n".join(verdict.lines)
    assert re.findall(r"\d+", text) == ["100", "85", "100", "85", "0", "10", "3"]
    for word in ("nudity", "explicit"):  # "safe" and "suggestive" are in the fixed text
        assert word not in text


def test_a_planted_level_never_reaches_repr_or_the_default_output() -> None:
    row = gate_3.Outcome(("x.png",), "classified", "zorbs", "plinth", "safe", PLANTED)
    assert PLANTED not in repr(row) and PLANTED not in str(row)
    lset = level_labels(["x.png,zorbs,plinth,no,,,,"])
    m = gate_3.evaluate(lset, [row], MIN_LEVEL)  # an unknown level is a miss, never quoted
    assert m.safe.hit == 0
    assert PLANTED not in "\n".join(gate_3.judge(m, detail=True).lines)
