"""The two-axis decision rules (CLS-002.1): pure, numeric scores, artificial category names."""

import pytest

from classifier.config import AxisConfig, ClassifyConfig
from classifier.models import classify_rules as rules_mod
from classifier.models.classify_rules import (
    CategoryRule,
    ClassifyRulesError,
    _pick_axis,
    _rank,
    nsfw_branch,
    top_scores,
    validate_rules,
)


def cfg(
    fmt_default: float | None = 0.5,
    topic_default: float | None = 0.5,
    fmt_margin: float = 0.05,
    topic_margin: float = 0.05,
) -> ClassifyConfig:
    return ClassifyConfig(
        score="sigmoid",
        format=AxisConfig(default_min_score=fmt_default, margin=fmt_margin),
        topic=AxisConfig(default_min_score=topic_default, margin=topic_margin),
    )


_ids = iter(range(1, 10_000))


def rule(
    name: str,
    axis: str = "format",
    min_score: float | None = None,
    branch: str = "any",
    parent_id: int | None = None,
    id: int | None = None,
) -> CategoryRule:
    return CategoryRule(
        id=id if id is not None else next(_ids),
        axis=axis,
        name=name,
        folder=name.title(),
        min_score=min_score,
        branch=branch,
        parent_id=parent_id,
    )


def pick(scores: dict[str, float], rules: list[CategoryRule], axis: str = "format", config=None):
    config = config or cfg()
    ranked = _rank(scores, [r for r in rules if r.axis == axis])
    winner = _pick_axis(ranked, rules_mod._axis_config(axis, config), axis)
    return winner.name if winner else None


def test_nsfw_branch_threshold_is_inclusive():
    assert nsfw_branch(0.69, 0.70) == "safe"
    assert nsfw_branch(0.70, 0.70) == "nsfw"
    assert nsfw_branch(0.99, 0.70) == "nsfw"
    assert nsfw_branch(0.0, 0.70) == "safe"


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_nsfw_branch_refuses_non_finite(bad):
    with pytest.raises(ClassifyRulesError):
        nsfw_branch(bad, 0.7)
    with pytest.raises(ClassifyRulesError):
        nsfw_branch(0.5, bad)


def test_clear_winner():
    rules = [rule("qorvex"), rule("zhyndel")]
    assert pick({"qorvex": 0.9, "zhyndel": 0.2}, rules) == "qorvex"


def test_single_candidate_has_no_margin_to_beat():
    assert pick({"qorvex": 0.6}, [rule("qorvex")]) == "qorvex"


def test_below_min_score_has_no_winner():
    rules = [rule("qorvex"), rule("zhyndel")]
    assert pick({"qorvex": 0.49, "zhyndel": 0.1}, rules) is None


def test_min_score_is_inclusive():
    assert pick({"qorvex": 0.5}, [rule("qorvex")]) == "qorvex"


def test_margin_fail_and_inclusive_boundary():
    rules = [rule("qorvex"), rule("zhyndel")]
    assert pick({"qorvex": 0.80, "zhyndel": 0.78}, rules) is None
    assert pick({"qorvex": 0.80, "zhyndel": 0.75}, rules) == "qorvex"
    # 0.60 - 0.55 is 0.04999... in floats: still at the margin
    assert pick({"qorvex": 0.60, "zhyndel": 0.55}, rules) == "qorvex"


def test_own_min_score_overrides_the_axis_default():
    rules = [rule("qorvex", min_score=0.9), rule("zhyndel")]
    assert pick({"qorvex": 0.8, "zhyndel": 0.1}, rules) is None
    assert pick({"qorvex": 0.95, "zhyndel": 0.1}, rules) == "qorvex"
    # a null min_score takes the axis default of the rule's own axis
    assert pick({"zhyndel": 0.7}, rules, config=cfg(fmt_default=0.8)) is None
    assert pick({"zhyndel": 0.7}, rules, config=cfg(fmt_default=0.6)) == "zhyndel"


def test_topic_axis_uses_its_own_default_and_margin():
    rules = [rule("vrelk", axis="topic"), rule("ploon", axis="topic")]
    config = cfg(topic_default=0.3, topic_margin=0.2)
    assert pick({"vrelk": 0.5, "ploon": 0.4}, rules, "topic", config) is None
    assert pick({"vrelk": 0.5, "ploon": 0.3}, rules, "topic", config) == "vrelk"


def test_ties_sort_by_score_then_name():
    ranked = _rank(
        {"zhyndel": 0.7, "qorvex": 0.7, "vrelk": 0.9},
        [rule("zhyndel"), rule("qorvex"), rule("vrelk")],
    )
    assert [r.name for r, _ in ranked] == ["vrelk", "qorvex", "zhyndel"]


def test_tied_pair_fails_the_margin_whoever_sorts_first():
    rules = [rule("zhyndel"), rule("qorvex")]
    assert pick({"zhyndel": 0.7, "qorvex": 0.7}, rules) is None


def test_unsorted_and_unscored_rules_are_not_candidates():
    rules = [rule("unsorted"), rule("qorvex"), rule("zhyndel")]
    ranked = _rank({"unsorted": 0.99, "qorvex": 0.6, "stray": 0.9}, rules)
    assert [r.name for r, _ in ranked] == ["qorvex"]


def test_non_finite_score_is_refused():
    with pytest.raises(ClassifyRulesError):
        _rank({"qorvex": float("nan")}, [rule("qorvex")])


def test_null_default_with_a_null_min_score_raises_naming_the_key():
    with pytest.raises(ClassifyRulesError, match=r"classify\.format\.default_min_score"):
        pick({"qorvex": 0.9}, [rule("qorvex")], config=cfg(fmt_default=None))
    with pytest.raises(ClassifyRulesError, match=r"classify\.topic\.default_min_score"):
        pick({"vrelk": 0.9}, [rule("vrelk", "topic")], "topic", cfg(topic_default=None))


def test_null_default_is_fine_when_the_winner_has_its_own_min_score():
    assert pick({"qorvex": 0.9}, [rule("qorvex", min_score=0.4)], config=cfg(None)) == "qorvex"


def test_top_scores_are_the_best_five_rounded_in_order():
    scores = {f"cat{i}": 0.1 * i + 0.00004 for i in range(1, 8)}
    ranked = _rank(scores, [rule(n) for n in scores])
    top = top_scores(ranked)
    assert [t["category"] for t in top] == ["cat7", "cat6", "cat5", "cat4", "cat3"]
    assert top[0]["score"] == 0.7 and top[1]["score"] == 0.6
    assert top_scores(_rank({"qorvex": 0.123456}, [rule("qorvex")])) == [
        {"category": "qorvex", "score": 0.1235}
    ]


# ---- validate_rules (CLS-002.D4, up front)


def test_valid_rules_pass():
    parent = rule("vrelk", "topic", id=900)
    validate_rules(
        [rule("qorvex"), rule("unsorted"), parent, rule("ploon", "topic", parent_id=900)], cfg()
    )


def test_validate_null_min_score_with_null_default_names_the_key():
    with pytest.raises(ClassifyRulesError, match=r"classify\.format\.default_min_score"):
        validate_rules([rule("qorvex")], cfg(fmt_default=None))
    with pytest.raises(ClassifyRulesError, match=r"classify\.topic\.default_min_score"):
        validate_rules([rule("vrelk", "topic")], cfg(topic_default=None))


def test_validate_null_default_is_fine_when_every_rule_sets_min_score():
    validate_rules([rule("qorvex", min_score=0.5), rule("unsorted")], cfg(None, None))


def test_validate_refuses_bad_axis_branch_and_duplicates():
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex", axis="colour")], cfg())
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex", branch="adult")], cfg())
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex"), rule("qorvex")], cfg())
    # the same name on the two axes is allowed (CLS-001.D10)
    validate_rules([rule("zhyndel"), rule("zhyndel", "topic")], cfg())


def test_validate_refuses_missing_cross_axis_and_looping_parents():
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex", parent_id=404)], cfg())
    other_axis = rule("vrelk", "topic", id=910)
    with pytest.raises(ClassifyRulesError):
        validate_rules([other_axis, rule("qorvex", parent_id=910)], cfg())
    with pytest.raises(ClassifyRulesError):
        validate_rules(
            [rule("qorvex", id=920, parent_id=921), rule("zhyndel", id=921, parent_id=920)], cfg()
        )
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex", id=930, parent_id=930)], cfg())
