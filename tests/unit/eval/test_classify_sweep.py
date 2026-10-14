"""The calibration sweep (CLS-003.1): synthetic scores, synthetic labels, artificial names.

Nothing here reads fixtures or loads a model. Category names are coinages, scores are drawn
from a seeded generator, and no adult content exists: the NSFW rows are bare numbers.
"""

import random
import sys
from pathlib import Path

import pytest

from classifier.config import AxisConfig, ClassifyConfig
from classifier.models.classify_rules import UNSORTED, CategoryRule

EVAL = Path(__file__).resolve().parents[3] / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))

import classify_sweep as sweep  # noqa: E402
from classify_sweep import AxisFit, Item, Metrics  # noqa: E402

FORMATS = ("Qorvex", "Zhyndel", "Vlarn")
TOPICS = ("Blip", "Quarn", "Zhyndel")  # the last one repeats a format name: the twin (R-CLS-3b)


def base_config() -> ClassifyConfig:
    return ClassifyConfig(
        score="sigmoid",
        format=AxisConfig(default_min_score=None, margin=0.05),
        topic=AxisConfig(default_min_score=None, margin=0.05),
    )


def rules() -> list[CategoryRule]:
    out, next_id = [], 1
    for axis, names in (("format", (*FORMATS, UNSORTED)), ("topic", TOPICS)):
        for name in names:
            out.append(CategoryRule(next_id, axis, name, name, None, "any", None))
            next_id += 1
    return out


def scores(names, label, true_score, rng) -> dict[str, float]:
    return {n: (true_score if n == label else rng.uniform(0.02, 0.12)) for n in names}


def make_items(n=45, hard_format=None, hard_rows=None, seed=3) -> list[Item]:
    """`n` items; `hard_format` scores low (0.25) where the others score ~0.7, on its first
    `hard_rows` rows (all of them by default)."""
    rng = random.Random(seed)
    items = []
    for i in range(n):
        fmt = FORMATS[i % 3]
        topic = TOPICS[(i // 3) % 3] if i % 7 else None
        if topic == fmt:
            topic = None  # CLS-001.D10: a label never repeats its format
        hard = fmt == hard_format and (hard_rows is None or i < 3 * hard_rows)
        true_f = 0.25 if hard else rng.uniform(0.6, 0.8)
        topic_scores = scores(TOPICS, topic, rng.uniform(0.55, 0.75), rng)
        if fmt == "Zhyndel":
            topic_scores["Zhyndel"] = 0.8  # the twin scores high: it must be dropped first
        items.append(
            Item(
                format_scores=scores(FORMATS, fmt, true_f, rng),
                topic_scores=topic_scores,
                nsfw=rng.uniform(0.02, 0.2) if i % 5 else rng.uniform(0.85, 0.99),
                format=fmt,
                topic=topic,
                adult=i % 5 == 0,
                suggestive_negative=i % 11 == 1,
                calibration_only=False,
            )
        )
    return items


def nsfw_item(score: float, adult: bool, calibration_only: bool = False) -> Item:
    return Item({}, {}, score, None, None, adult, False, calibration_only)


@pytest.fixture
def coarse(monkeypatch):
    """A coarser grid keeps the cross-validation test fast; the logic is the same."""
    monkeypatch.setattr(sweep, "COARSE_STEP", 0.1)
    monkeypatch.setattr(sweep, "FINE_SPAN", 1)


# --- NSFW threshold ---------------------------------------------------------------------


def test_nsfw_threshold_is_the_middle_of_the_feasible_interval():
    items = [nsfw_item(0.1, False), nsfw_item(0.3, False), nsfw_item(0.9, True)]
    assert sweep.fit_nsfw(items) == 0.6


def test_calibration_only_rows_count_for_the_nsfw_sweep():
    items = [nsfw_item(0.1, False), nsfw_item(0.9, True), nsfw_item(0.5, True, True)]
    assert sweep.fit_nsfw(items) == 0.3


def test_nsfw_with_no_feasible_threshold_is_none_and_never_relaxed():
    assert sweep.fit_nsfw([nsfw_item(0.8, False), nsfw_item(0.6, True)]) is None


def test_the_fitted_threshold_flags_every_adult_row_and_no_other():
    items = make_items()
    threshold = sweep.fit_nsfw(items)
    assert all((item.nsfw >= threshold) == item.adult for item in items)


# --- Measures ---------------------------------------------------------------------------


def test_measure_counts_gate_rows_only():
    items = make_items(12)
    extra = Item(
        {n: 0.0 for n in FORMATS}, {}, 0.5, "Qorvex", None, False, False, calibration_only=True
    )
    rule_set, cfg = sweep.materialize(
        rules(), base_config(), AxisFit(0.3, 0.05), AxisFit(0.3, 0.05)
    )
    with_extra = sweep.measure([*items, extra], rule_set, cfg, 0.6)
    assert with_extra == sweep.measure(items, rule_set, cfg, 0.6)
    assert with_extra.rows == 12


def test_measure_flags_a_wrongly_flagged_suggestive_negative_row():
    safe_looking = Item({"Qorvex": 0.9}, {}, 0.8, "Qorvex", None, False, True, False)
    rule_set, cfg = sweep.materialize(
        rules(), base_config(), AxisFit(0.3, 0.05), AxisFit(0.3, 0.05)
    )
    result = sweep.measure([safe_looking], rule_set, cfg, 0.5)
    assert not result.suggestive_ok
    assert not result.adult_ok


# --- Axis sweep -------------------------------------------------------------------------


def test_sweep_takes_the_conservative_end_when_agreement_holds():
    items = make_items()
    fit = sweep.sweep_axis(items, rules(), base_config(), 0.6, "format")
    assert fit.default_min_score >= 0.5  # not the degenerate 0.02 that agreement alone prefers
    rule_set, cfg = sweep.materialize(rules(), base_config(), fit, AxisFit(0.5, 0.0))
    assert sweep.measure(items, rule_set, cfg, 0.6).format_correct == 45


def test_sweep_drops_the_bar_when_a_slack_of_one_point_would_lose_rows():
    items = make_items(hard_format="Vlarn")  # a third of the rows score 0.25
    fit = sweep.sweep_axis(items, rules(), base_config(), 0.6, "format")
    assert fit.default_min_score <= 0.25


def test_topic_sweep_drops_the_twin_before_judging():
    items = make_items()
    fmt = sweep.sweep_axis(items, rules(), base_config(), 0.6, "format")
    topic = sweep.sweep_axis(items, rules(), base_config(), 0.6, "topic", fmt)
    rule_set, cfg = sweep.materialize(rules(), base_config(), fmt, topic)
    result = sweep.measure(items, rule_set, cfg, 0.6)
    assert result.topic_correct >= result.topic_total - 1


def test_a_topic_sweep_without_a_format_fit_is_refused():
    with pytest.raises(sweep.SweepError) as caught:
        sweep.sweep_axis(make_items(), rules(), base_config(), 0.6, "topic")
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_an_empty_gate_set_is_refused_with_fixed_text():
    only_calibration = [nsfw_item(0.5, False, True)]
    with pytest.raises(sweep.SweepError, match="no gate rows"):
        sweep.sweep_axis(only_calibration, rules(), base_config(), 0.6, "format")


# --- Overrides --------------------------------------------------------------------------


def test_an_override_is_proposed_only_where_it_wins_whole_rows():
    items = make_items(hard_format="Vlarn")
    fit = AxisFit(0.5, 0.05)
    out = sweep.fit_overrides(items, rules(), base_config(), 0.6, "format", fit)
    assert dict(out.overrides) == {"Vlarn": pytest.approx(0.22)} or [
        name for name, _ in out.overrides
    ] == ["Vlarn"]
    assert 0 < dict(out.overrides)["Vlarn"] <= 0.25


def test_no_override_when_the_default_already_covers_every_category():
    out = sweep.fit_overrides(
        make_items(), rules(), base_config(), 0.6, "format", AxisFit(0.3, 0.05)
    )
    assert out.overrides == ()


# --- The whole calibration --------------------------------------------------------------


def test_calibrate_with_a_hard_category_keeps_an_override_that_survives_the_folds(coarse):
    items = make_items(n=60, hard_format="Vlarn", hard_rows=3)
    result = sweep.calibrate(items, rules(), base_config(), slack_points=5.0)
    assert result.feasible
    assert [name for name, _ in result.format.overrides] == ["Vlarn"]
    assert result.format_overrides_survive is True
    assert result.fitted.format_correct == result.fitted.format_total
    assert not sweep.has_concerns(result.fitted, result.held_out)
    again = sweep.calibrate(items, rules(), base_config(), slack_points=5.0)
    assert again == result  # pinned seed


def test_calibrate_proposes_nothing_for_categories_when_nsfw_is_infeasible():
    items = [*make_items(10), nsfw_item(0.99, False), nsfw_item(0.01, True)]
    result = sweep.calibrate(items, rules(), base_config())
    assert not result.feasible
    assert not result.fitted.adult_ok
    assert result.format.overrides == () and result.topic.overrides == ()


def test_a_gap_over_five_points_is_a_concern():
    fitted = Metrics(format_correct=95, format_total=100, topic_correct=90, topic_total=100)
    close = Metrics(format_correct=91, format_total=100, topic_correct=88, topic_total=100)
    far = Metrics(format_correct=89, format_total=100, topic_correct=88, topic_total=100)
    assert not sweep.has_concerns(fitted, close)
    assert sweep.has_concerns(fitted, far)


def test_per_category_detail_has_one_row_per_label():
    items = make_items(12)
    rule_set, cfg = sweep.materialize(
        rules(), base_config(), AxisFit(0.3, 0.05), AxisFit(0.3, 0.05)
    )
    detail = sweep.per_category(items, rule_set, cfg, 0.6)
    assert set(detail["format"]) == set(FORMATS)


# --- Privacy (checklist 4) --------------------------------------------------------------


def test_reprs_hold_no_label_name_or_score():
    secret = "Xqzvt-planted"
    item = Item({secret: 0.7123}, {secret: 0.7123}, 0.4411, secret, secret, True, True, True)
    fit = AxisFit(0.3377, 0.0511, ((secret, 0.2288),))
    metrics = Metrics(format_correct=777, format_total=888)
    calibration = sweep.Calibration(True, 0.5599, fit, fit, metrics, metrics, True, True)
    for obj in (item, fit, metrics, calibration):
        for text in (repr(obj), str(obj)):
            assert secret not in text
            for number in (
                "0.7123",
                "0.4411",
                "0.3377",
                "0.0511",
                "0.2288",
                "777",
                "888",
                "0.5599",
            ):
                assert number not in text


# --- CLS-003.1.6 ------------------------------------------------------------------------


def test_the_diagnostic_counts_the_two_kinds_of_miss_at_the_best_threshold():
    items = [
        nsfw_item(0.9, True),
        nsfw_item(0.8, True),
        nsfw_item(0.3, True),
        nsfw_item(0.1, False),
        nsfw_item(0.2, False),
        nsfw_item(0.5, False, True),  # a safe calibration-only row that scores high
    ]
    found = sweep.nsfw_diagnostic(items)
    assert found.adult_below + found.safe_above == 1  # one miss is the best any threshold does


def test_holding_the_threshold_skips_the_nsfw_sweep_and_still_fits_the_categories(coarse):
    items = make_items(n=45)
    infeasible = [*items, nsfw_item(0.99, False), nsfw_item(0.01, True)]
    assert not sweep.calibrate(infeasible, rules(), base_config()).feasible
    held = sweep.calibrate(infeasible, rules(), base_config(), hold_nsfw=0.7)
    assert held.feasible and held.nsfw_held and held.nsfw_threshold == 0.7
    assert not held.fitted.adult_ok  # measured at the held value: the two extra rows miss
    assert held.fitted.format_total > 0
