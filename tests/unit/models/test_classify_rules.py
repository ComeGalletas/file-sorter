"""The two-axis decision rules (CLS-002.1): pure, numeric scores, artificial category names."""

import ast
from pathlib import Path

import pytest

from classifier.config import AxisConfig, ClassifyConfig, CrossCheckConfig, NsfwConfig, NsfwLevel
from classifier.models import classify_rules as rules_mod
from classifier.models.classify_rules import (
    CategoryRule,
    ClassifyRulesError,
    VlmAnswer,
    _pick_axis,
    _rank,
    branch_for_level,
    nsfw_branch,
    nsfw_cross_check,
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
    by_id = {r.id: r for r in rules}
    winner = _pick_axis(ranked, rules_mod._axis_config(axis, config), axis, by_id)
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


# ---- nesting (R-CLS-4, CLS-002.D6)


def nested(axis: str = "format"):
    parent = rule("qorvex", axis, id=800)
    child = rule("qorvex-zhyndel", axis, id=801, parent_id=800)
    other = rule("vrelk", axis, id=802)
    return parent, child, other


def test_deeper_wins_inside_the_margin_when_it_clears_its_min_score():
    parent, child, other = nested()
    # the ancestor leads by less than the margin, or even trails: the margin is skipped
    scores = {"qorvex": 0.80, "qorvex-zhyndel": 0.79, "vrelk": 0.1}
    assert pick(scores, [parent, child, other]) == "qorvex-zhyndel"
    scores = {"qorvex": 0.79, "qorvex-zhyndel": 0.80, "vrelk": 0.1}
    assert pick(scores, [parent, child, other]) == "qorvex-zhyndel"


def test_deeper_failing_its_own_min_score_leaves_the_ancestor_to_the_normal_rule():
    parent = rule("qorvex", id=810)
    child = rule("qorvex-zhyndel", id=811, parent_id=810, min_score=0.9)
    other = rule("vrelk", id=812)
    rules = [parent, child, other]
    # the ancestor beats the next non-descendant by the margin: it wins
    assert pick({"qorvex": 0.80, "qorvex-zhyndel": 0.79, "vrelk": 0.3}, rules) == "qorvex"
    # the failed descendant is not the ancestor's competitor; the other category is
    assert pick({"qorvex": 0.80, "qorvex-zhyndel": 0.79, "vrelk": 0.78}, rules) is None
    # the ancestor must also clear its own min_score
    assert pick({"qorvex": 0.40, "qorvex-zhyndel": 0.39, "vrelk": 0.1}, rules) is None


def test_ancestor_with_only_a_failed_descendant_wins_on_min_score():
    parent = rule("qorvex", id=820)
    child = rule("qorvex-zhyndel", id=821, parent_id=820, min_score=0.9)
    assert pick({"qorvex": 0.6, "qorvex-zhyndel": 0.5}, [parent, child]) == "qorvex"


def test_unrelated_top_two_use_the_margin():
    parent, child, other = nested()
    scores = {"vrelk": 0.80, "qorvex": 0.78, "qorvex-zhyndel": 0.1}
    assert pick(scores, [parent, child, other]) is None


def test_nesting_works_on_the_topic_axis_and_across_levels():
    root = rule("vrelk", "topic", id=830)
    mid = rule("vrelk-ploon", "topic", id=831, parent_id=830)
    leaf = rule("vrelk-ploon-snax", "topic", id=832, parent_id=831)
    rules = [root, mid, leaf]
    assert pick({"vrelk": 0.8, "vrelk-ploon-snax": 0.79}, rules, "topic") == "vrelk-ploon-snax"
    assert pick({"vrelk": 0.8, "vrelk-ploon": 0.79}, rules, "topic") == "vrelk-ploon"


def test_a_looping_chain_does_not_hang_the_pick():
    a = rule("qorvex", id=840, parent_id=841)
    b = rule("zhyndel", id=841, parent_id=840)
    # validate_rules refuses this; the pick still terminates, and judges `a` on its own
    assert pick({"qorvex": 0.9, "zhyndel": 0.1}, [a, b]) == "qorvex"


# ---- choose (R-CLS-3, 3a, 3b, 6; CLS-002.D2, D3, D5)

FMT = [rule("qorvex"), rule("zhyndel"), rule("snaxel")]
TOP = [rule("vrelk", "topic"), rule("ploon", "topic"), rule("zhyndel", "topic")]
ALL = FMT + TOP + [rule("unsorted")]


def decide(fmt, topic, rules=None, branch="safe", config=None):
    return rules_mod.choose(fmt, topic, rules or ALL, branch, config or cfg())


def test_format_and_topic_both_chosen():
    got = decide({"qorvex": 0.9, "zhyndel": 0.1}, {"vrelk": 0.8, "ploon": 0.2})
    assert (got.format, got.topic) == ("qorvex", "vrelk")
    assert got.needs_review is False and got.review_reason is None


def test_no_format_winner_is_unsorted_and_a_review_case():
    got = decide({"qorvex": 0.3, "zhyndel": 0.2}, {"vrelk": 0.8, "ploon": 0.2})
    assert got.format == "unsorted"
    assert got.needs_review is True and got.review_reason == "unsorted"
    assert got.topic == "vrelk"  # the best topic is still decided and recorded
    assert got.topic_top[0] == {"category": "vrelk", "score": 0.8}


def test_format_margin_failure_is_unsorted():
    got = decide({"qorvex": 0.80, "zhyndel": 0.78}, {"vrelk": 0.8})
    assert (got.format, got.needs_review) == ("unsorted", True)


def test_no_topic_winner_is_not_a_review_case():
    got = decide({"qorvex": 0.9}, {"vrelk": 0.3, "ploon": 0.2})
    assert (got.format, got.topic) == ("qorvex", None)
    assert got.needs_review is False and got.review_reason is None
    got = decide({"qorvex": 0.9}, {"vrelk": 0.80, "ploon": 0.78})  # topic margin fails
    assert got.topic is None and got.needs_review is False


def test_topic_axis_is_scored_with_its_own_config():
    config = cfg(topic_default=0.2, topic_margin=0.5)
    assert decide({"qorvex": 0.9}, {"vrelk": 0.6, "ploon": 0.2}, config=config).topic is None
    config = cfg(topic_default=0.7)
    assert decide({"qorvex": 0.9}, {"vrelk": 0.6, "ploon": 0.2}, config=config).topic is None


def test_twin_of_the_format_is_removed_from_the_topic_candidates():
    # zhyndel is both a format and a topic; the topic twin leads but is skipped
    topic = {"zhyndel": 0.95, "vrelk": 0.70, "ploon": 0.2}
    got = decide({"zhyndel": 0.9, "qorvex": 0.1}, topic)
    assert (got.format, got.topic) == ("zhyndel", "vrelk")
    assert got.topic_top[0]["category"] == "zhyndel"  # the top 5 stays unfiltered (D5)


def test_twin_removal_takes_the_margin_against_the_next_remaining_topic():
    # without the twin, vrelk (0.70) vs ploon (0.68) fails the margin: no topic
    topic = {"zhyndel": 0.95, "vrelk": 0.70, "ploon": 0.68}
    got = decide({"zhyndel": 0.9, "qorvex": 0.1}, topic)
    assert (got.format, got.topic) == ("zhyndel", None)


def test_a_twin_that_is_not_the_format_is_a_normal_competitor():
    topic = {"zhyndel": 0.95, "vrelk": 0.70, "ploon": 0.2}
    got = decide({"qorvex": 0.9, "zhyndel": 0.1}, topic)
    assert got.topic == "zhyndel"


def test_twin_is_not_removed_when_the_format_is_unsorted():
    topic = {"zhyndel": 0.95, "vrelk": 0.5, "ploon": 0.2}
    got = decide({"qorvex": 0.3, "zhyndel": 0.2}, topic)
    assert (got.format, got.topic) == ("unsorted", "zhyndel")


def test_format_winner_excluded_by_the_branch_goes_to_unsorted_not_the_runner_up():
    rules = [rule("qorvex", branch="safe"), rule("zhyndel")] + TOP
    fmt = {"qorvex": 0.9, "zhyndel": 0.5}
    adult = decide(fmt, {"vrelk": 0.8}, rules, branch="nsfw")
    assert (adult.format, adult.needs_review, adult.review_reason) == ("unsorted", True, "unsorted")
    assert decide(fmt, {"vrelk": 0.8}, rules, branch="safe").format == "qorvex"
    rules = [rule("qorvex", branch="nsfw"), rule("zhyndel")] + TOP
    assert decide(fmt, {"vrelk": 0.8}, rules, branch="safe").format == "unsorted"
    assert decide(fmt, {"vrelk": 0.8}, rules, branch="nsfw").format == "qorvex"


def test_topic_winner_excluded_by_the_branch_is_no_topic_not_the_runner_up():
    rules = FMT + [rule("vrelk", "topic", branch="safe"), rule("ploon", "topic")]
    topic = {"vrelk": 0.9, "ploon": 0.5}
    adult = decide({"qorvex": 0.9}, topic, rules, branch="nsfw")
    assert (adult.format, adult.topic, adult.needs_review) == ("qorvex", None, False)
    assert decide({"qorvex": 0.9}, topic, rules, branch="safe").topic == "vrelk"
    rules = FMT + [rule("vrelk", "topic", branch="nsfw"), rule("ploon", "topic")]
    assert decide({"qorvex": 0.9}, topic, rules, branch="safe").topic is None
    assert decide({"qorvex": 0.9}, topic, rules, branch="nsfw").topic == "vrelk"


@pytest.mark.parametrize("branch", ["safe", "nsfw"])
def test_per_axis_branch_combinations(branch):
    other = "nsfw" if branch == "safe" else "safe"
    for fmt_branch in ("any", branch, other):
        for topic_branch in ("any", branch, other):
            rules = [
                rule("qorvex", branch=fmt_branch),
                rule("zhyndel"),
                rule("vrelk", "topic", branch=topic_branch),
                rule("ploon", "topic"),
            ]
            fmt = {"qorvex": 0.9, "zhyndel": 0.1}
            got = decide(fmt, {"vrelk": 0.9, "ploon": 0.1}, rules, branch)
            assert got.format == ("qorvex" if fmt_branch in ("any", branch) else "unsorted")
            assert got.topic == ("vrelk" if topic_branch in ("any", branch) else None)
            assert got.needs_review == (fmt_branch == other)


def test_unsorted_is_always_eligible_whatever_its_row_says():
    rules = [rule("unsorted", branch="safe"), rule("qorvex", branch="safe")]
    assert decide({"qorvex": 0.9}, {}, rules, branch="nsfw").format == "unsorted"


def test_choose_rejects_an_unknown_branch():
    with pytest.raises(ClassifyRulesError):
        decide({"qorvex": 0.9}, {}, branch="adult")


def test_choose_backstops_the_null_default():
    with pytest.raises(ClassifyRulesError, match=r"classify\.format\.default_min_score"):
        decide({"qorvex": 0.9}, {}, config=cfg(fmt_default=None))
    with pytest.raises(ClassifyRulesError, match=r"classify\.topic\.default_min_score"):
        decide({"qorvex": 0.9}, {}, config=cfg(topic_default=None))
    # every rule has its own min_score: a null default is fine
    rules = [rule("qorvex", min_score=0.5), rule("vrelk", "topic", min_score=0.5)]
    got = decide({"qorvex": 0.9}, {"vrelk": 0.9}, rules, config=cfg(None, None))
    assert got.topic == "vrelk"


def test_stored_scores_are_the_top_five_in_four_decimals():
    names = [f"cat{i}" for i in range(7)]
    rules = [rule(n) for n in names] + [rule("vrelk", "topic")]
    fmt = {n: 0.1 + i * 0.1 + 0.00004 for i, n in enumerate(names)}
    got = decide(fmt, {"vrelk": 0.51234}, rules)
    assert [t["category"] for t in got.format_top] == names[::-1][:5]
    assert got.format_top[0]["score"] == 0.7
    assert got.topic_top == [{"category": "vrelk", "score": 0.5123}]


def test_empty_scores_give_unsorted_and_no_topic():
    got = decide({}, {})
    assert (got.format, got.topic, got.needs_review) == ("unsorted", None, True)
    assert got.format_top == [] and got.topic_top == []


def test_choose_is_deterministic_under_ties():
    rules = [rule("qorvex"), rule("zhyndel"), rule("vrelk", "topic"), rule("ploon", "topic")]
    first = decide({"qorvex": 0.9, "zhyndel": 0.9}, {"vrelk": 0.9, "ploon": 0.9}, rules)
    again = decide(
        {"zhyndel": 0.9, "qorvex": 0.9}, {"ploon": 0.9, "vrelk": 0.9}, list(reversed(rules))
    )
    assert first.format_top == again.format_top and first.topic_top == again.topic_top
    assert first.format == again.format == "unsorted"


# ---- privacy (checklist 2, 4, 5, 7)

SECRET_NAME = "Qorvex-Planted-Name"
SECRET_FOLDER = "Zhyndel-Planted-Folder"
SECRET_SCORE = 0.31415926


def test_repr_and_str_hide_every_name_folder_and_threshold():
    planted = CategoryRule(
        id=7,
        axis="format",
        name=SECRET_NAME,
        folder=SECRET_FOLDER,
        min_score=SECRET_SCORE,
        branch="any",
        parent_id=None,
    )
    topic = CategoryRule(7 + 1, "topic", "Vrelk-Planted-Topic", SECRET_FOLDER, 0.2, "any", None)
    got = rules_mod.choose(
        {SECRET_NAME: 0.97654321}, {"Vrelk-Planted-Topic": 0.8}, [planted, topic], "safe", cfg()
    )
    assert got.format == SECRET_NAME and got.topic == "Vrelk-Planted-Topic"
    for text in (repr(planted), str(planted), repr(got), str(got)):
        for secret in (SECRET_NAME, SECRET_FOLDER, "Vrelk-Planted-Topic", "0.3141", "0.9765"):
            assert secret not in text


@pytest.mark.parametrize(
    "call",
    [
        lambda: nsfw_branch(float("nan"), 0.7),
        lambda: validate_rules([rule(SECRET_NAME, branch="adult")], cfg()),
        lambda: validate_rules([rule(SECRET_NAME, axis="colour")], cfg()),
        lambda: validate_rules([rule(SECRET_NAME), rule(SECRET_NAME)], cfg()),
        lambda: validate_rules([rule(SECRET_NAME, parent_id=404)], cfg()),
        lambda: validate_rules([rule(SECRET_NAME)], cfg(fmt_default=None)),
        lambda: rules_mod.choose(
            {SECRET_NAME: float("nan")}, {}, [rule(SECRET_NAME)], "safe", cfg()
        ),
        lambda: rules_mod.choose({}, {}, [rule(SECRET_NAME)], "adult", cfg()),
        lambda: rules_mod.choose({SECRET_NAME: 0.9}, {}, [rule(SECRET_NAME)], "safe", cfg(None)),
    ],
)
def test_errors_are_fixed_text_and_unchained(call):
    with pytest.raises(ClassifyRulesError) as caught:
        call()
    error = caught.value
    assert error.__cause__ is None and error.__context__ is None
    assert SECRET_NAME not in str(error) and SECRET_NAME not in repr(error)


def test_lone_surrogates_in_names_are_only_compared_never_quoted():
    odd = "Qorvex-\ud800-lone"
    rules = [rule(odd), rule("zhyndel")]
    got = rules_mod.choose({odd: 0.9, "zhyndel": 0.1}, {}, rules, "safe", cfg())
    assert got.format == odd
    assert got.format_top[0]["category"] == odd
    with pytest.raises(ClassifyRulesError) as caught:
        validate_rules([rule(odd), rule(odd)], cfg())
    assert "\ud800" not in str(caught.value)


def test_the_module_has_no_io_imports():
    tree = ast.parse(Path(rules_mod.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"math", "collections", "dataclasses", "typing", "classifier"}
    assert not any(
        isinstance(n, ast.Call) and getattr(n.func, "id", "") in ("open", "print")
        for n in ast.walk(tree)
    )


# ---- the VLM path (CLS-004.3; CLS-004.D3, D7)


@pytest.mark.parametrize("min_level", list(NsfwLevel))
@pytest.mark.parametrize("level", list(NsfwLevel))
def test_branch_for_level_is_adult_at_or_above_min_level(level, min_level):
    assert branch_for_level(level, min_level) == ("nsfw" if level >= min_level else "safe")


def test_branch_for_level_at_the_human_setting_nudity():
    got = [branch_for_level(level, NsfwLevel.nudity) for level in NsfwLevel]
    assert got == ["safe", "safe", "nsfw", "nsfw"]


def test_levels_are_ordered():
    assert NsfwLevel.safe < NsfwLevel.suggestive < NsfwLevel.nudity < NsfwLevel.explicit


@pytest.mark.parametrize("bad", [2, 2.0, "nudity", None, True])
def test_branch_for_level_refuses_non_levels_with_fixed_text(bad):
    for args in ((bad, NsfwLevel.nudity), (NsfwLevel.nudity, bad)):
        with pytest.raises(ClassifyRulesError) as caught:
            branch_for_level(*args)
        assert caught.value.__cause__ is None and caught.value.__context__ is None
        assert str(caught.value) == rules_mod._ERR_LEVEL


def test_validate_rules_without_a_config_does_not_need_a_default():
    rules = [rule("qorvex"), rule("vrelk", "topic")]  # no min_score anywhere
    validate_rules(rules)  # the VLM path: nothing to compare (D7)
    validate_rules(rules, None)
    with pytest.raises(ClassifyRulesError):
        validate_rules(rules, cfg(fmt_default=None))  # the SigLIP path still insists


def test_validate_rules_without_a_config_still_checks_structure():
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex"), rule("qorvex")])
    with pytest.raises(ClassifyRulesError):
        validate_rules([rule("qorvex", branch="sideways")])


def test_vlm_answer_is_a_plain_value():
    answer = VlmAnswer("qorvex", None, NsfwLevel.safe)
    assert (answer.format, answer.topic, answer.level) == ("qorvex", None, NsfwLevel.safe)


# ---- the Falconsai cross-check (CLS-004.D5)

BOTH = CrossCheckConfig(safe_above=0.8, adult_below=0.2)
OFF = CrossCheckConfig()


def check(level, score, cross=BOTH, min_level=NsfwLevel.nudity):
    return nsfw_cross_check(level, min_level, score, cross)


def test_safe_level_with_a_high_score_disagrees_inclusive():
    assert check(NsfwLevel.safe, 0.8) is True
    assert check(NsfwLevel.safe, 0.99) is True
    assert check(NsfwLevel.safe, 0.79) is False
    assert check(NsfwLevel.safe, 0.5) is False


def test_adult_level_with_a_low_score_disagrees_inclusive():
    for level in (NsfwLevel.nudity, NsfwLevel.explicit):
        assert check(level, 0.2) is True
        assert check(level, 0.0) is True
        assert check(level, 0.21) is False
        assert check(level, 0.9) is False


def test_agreement_and_the_middle_levels_do_not_disagree():
    assert check(NsfwLevel.safe, 0.01) is False  # both say safe
    assert check(NsfwLevel.explicit, 0.99) is False  # both say adult
    # suggestive is below min_level and not safe: neither half applies
    assert check(NsfwLevel.suggestive, 0.0) is False
    assert check(NsfwLevel.suggestive, 1.0) is False


def test_the_adult_half_follows_min_level():
    assert check(NsfwLevel.suggestive, 0.0, min_level=NsfwLevel.suggestive) is True
    assert check(NsfwLevel.nudity, 0.0, min_level=NsfwLevel.explicit) is False


def test_a_null_threshold_turns_only_its_half_off():
    only_safe = CrossCheckConfig(safe_above=0.8)
    only_adult = CrossCheckConfig(adult_below=0.2)
    assert check(NsfwLevel.safe, 0.9, only_safe) is True
    assert check(NsfwLevel.explicit, 0.0, only_safe) is False
    assert check(NsfwLevel.safe, 0.9, only_adult) is False
    assert check(NsfwLevel.explicit, 0.0, only_adult) is True


def test_both_null_is_off_and_no_score_is_off():
    for level in NsfwLevel:
        for score in (0.0, 0.5, 1.0):
            assert check(level, score, OFF) is False
        assert check(level, None) is False


def test_float_noise_does_not_flip_a_boundary():
    assert check(NsfwLevel.safe, 0.6 + 0.2 - 1e-12) is True  # 0.7999999...
    assert check(NsfwLevel.explicit, 0.1 + 0.1 + 1e-12) is True


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_non_finite_score_raises_fixed_text(bad):
    with pytest.raises(ClassifyRulesError) as caught:
        check(NsfwLevel.safe, bad)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert str(caught.value) == rules_mod._ERR_NSFW


def test_the_cross_check_refuses_non_levels():
    with pytest.raises(ClassifyRulesError):
        nsfw_cross_check(1, NsfwLevel.nudity, 0.5, BOTH)
    with pytest.raises(ClassifyRulesError):
        nsfw_cross_check(NsfwLevel.safe, "nudity", 0.5, BOTH)


def ncfg(min_level: str, cross_check: CrossCheckConfig) -> NsfwConfig:
    return NsfwConfig(min_level=min_level, cross_check=cross_check, mode="mirror", root="Adult")


NSFW = ncfg("nudity", BOTH)
VFMT = [
    rule("qorvex"),
    rule("zhyndel"),
    rule("snaxel", branch="nsfw"),
    rule("plimb", branch="safe"),
    rule("unsorted"),
]
VTOP = [
    rule("vrelk", "topic"),
    rule("ploon", "topic", branch="nsfw"),
    rule("grimble", "topic", branch="safe"),
    rule("zhyndel", "topic"),
]
VALL = VFMT + VTOP


def dec(fmt, topic=None, level=NsfwLevel.safe, score=None, rules=None, nsfw=NSFW):
    return rules_mod.decide(VlmAnswer(fmt, topic, level), rules or VALL, score, nsfw)


def test_decide_files_a_clean_answer_as_given():
    got = dec("qorvex", "vrelk")
    assert (got.branch, got.format, got.topic) == ("safe", "qorvex", "vrelk")
    assert (got.needs_review, got.review_reason) == (False, None)


def test_the_branch_comes_from_the_level_only():
    assert dec("qorvex", level=NsfwLevel.suggestive).branch == "safe"
    assert dec("qorvex", level=NsfwLevel.nudity).branch == "nsfw"
    assert dec("qorvex", level=NsfwLevel.explicit).branch == "nsfw"
    lowered = ncfg("suggestive", OFF)
    assert dec("qorvex", level=NsfwLevel.suggestive, nsfw=lowered).branch == "nsfw"


def test_an_nsfw_only_format_on_a_safe_image_is_unsorted_and_the_branch_stays():
    got = dec("snaxel", "vrelk", level=NsfwLevel.safe)
    assert (got.branch, got.format, got.topic) == ("safe", "unsorted", "vrelk")
    assert (got.needs_review, got.review_reason) == (True, "unsorted")


def test_a_safe_only_format_on_an_nsfw_image_is_unsorted_and_the_branch_stays():
    got = dec("plimb", "vrelk", level=NsfwLevel.explicit)
    assert (got.branch, got.format, got.topic) == ("nsfw", "unsorted", "vrelk")
    assert (got.needs_review, got.review_reason) == (True, "unsorted")


def test_each_branch_keeps_its_own_and_any_formats():
    assert dec("snaxel", level=NsfwLevel.nudity).format == "snaxel"
    assert dec("plimb", level=NsfwLevel.safe).format == "plimb"
    assert dec("qorvex", level=NsfwLevel.nudity).format == "qorvex"


def test_an_ineligible_topic_is_none_and_not_a_review_case():
    for topic, level in (("ploon", NsfwLevel.safe), ("grimble", NsfwLevel.nudity)):
        got = dec("qorvex", topic, level=level)
        assert got.topic is None
        assert (got.needs_review, got.review_reason) == (False, None)
    assert dec("qorvex", "ploon", level=NsfwLevel.nudity).topic == "ploon"


def test_an_answer_of_unsorted_is_a_review_case_and_the_topic_is_still_decided():
    got = dec("unsorted", "vrelk")
    assert (got.format, got.topic) == ("unsorted", "vrelk")
    assert (got.needs_review, got.review_reason) == (True, "unsorted")


def test_a_topic_named_like_the_chosen_format_is_dropped():
    got = dec("zhyndel", "zhyndel")
    assert (got.format, got.topic) == ("zhyndel", None)
    assert (got.needs_review, got.review_reason) == (False, None)


def test_the_twin_is_kept_when_the_format_did_not_survive():
    # "zhyndel" the topic, with the format unsorted: nothing is dropped
    assert dec("unsorted", "zhyndel").topic == "zhyndel"
    # the format is excluded by the branch, so it is not the chosen one either
    rules = [rule("vrelk", branch="nsfw"), rule("vrelk", "topic")]
    got = dec("vrelk", "vrelk", level=NsfwLevel.safe, rules=rules)
    assert (got.format, got.topic) == ("unsorted", "vrelk")


def test_no_topic_is_none():
    got = dec("qorvex", None)
    assert got.topic is None and got.needs_review is False


def test_min_score_and_margin_decide_nothing():
    rules = [rule("qorvex", min_score=0.99), rule("vrelk", "topic", min_score=1.0)]
    got = dec("qorvex", "vrelk", rules=rules)
    assert (got.format, got.topic, got.needs_review) == ("qorvex", "vrelk", False)


def test_a_disagreement_sets_needs_review_and_never_the_branch():
    got = dec("qorvex", "vrelk", level=NsfwLevel.safe, score=0.95)
    assert (got.branch, got.format, got.topic) == ("safe", "qorvex", "vrelk")
    assert (got.needs_review, got.review_reason) == (True, "nsfw_disagreement")
    got = dec("snaxel", level=NsfwLevel.explicit, score=0.05)
    assert (got.branch, got.format) == ("nsfw", "snaxel")
    assert (got.needs_review, got.review_reason) == (True, "nsfw_disagreement")


def test_a_disagreement_wins_over_unsorted_as_the_reason():
    got = dec("unsorted", level=NsfwLevel.safe, score=0.95)
    assert (got.format, got.needs_review, got.review_reason) == (
        "unsorted",
        True,
        "nsfw_disagreement",
    )
    got = dec("plimb", level=NsfwLevel.explicit, score=0.0)  # ineligible format too
    assert (got.format, got.review_reason) == ("unsorted", "nsfw_disagreement")


def test_agreement_missing_score_or_off_check_adds_no_review():
    assert dec("qorvex", level=NsfwLevel.safe, score=0.1).needs_review is False
    assert dec("qorvex", level=NsfwLevel.safe, score=None).needs_review is False
    off = ncfg("nudity", OFF)
    assert dec("qorvex", level=NsfwLevel.safe, score=0.99, nsfw=off).needs_review is False


def test_a_name_that_is_not_a_rule_of_its_axis_raises_fixed_text():
    cases = [
        ("Qorvex-Planted-Unknown", None),
        ("qorvex", "Vrelk-Planted-Unknown"),
        ("vrelk", None),  # a topic name on the format axis
        ("qorvex", "qorvex"),  # a format name on the topic axis
        ("qorvex", "unsorted"),  # unsorted is never a topic
    ]
    for fmt, topic in cases:
        with pytest.raises(ClassifyRulesError) as caught:
            dec(fmt, topic)
        error = caught.value
        assert error.__cause__ is None and error.__context__ is None
        assert str(error) == rules_mod._ERR_UNKNOWN
        assert "Planted" not in str(error) and "Planted" not in repr(error)


def test_vlm_types_hide_every_name_in_repr_and_str():
    planted = [
        rule("Qorvex-Planted-Name"),
        rule("Vrelk-Planted-Topic", "topic"),
    ]
    answer = VlmAnswer("Qorvex-Planted-Name", "Vrelk-Planted-Topic", NsfwLevel.safe)
    got = rules_mod.decide(answer, planted, 0.5, NSFW)
    assert got.format == "Qorvex-Planted-Name" and got.topic == "Vrelk-Planted-Topic"
    for obj in (answer, got):
        for text in (repr(obj), str(obj), f"{obj}"):
            assert "Planted" not in text


def test_a_lone_surrogate_name_is_compared_never_quoted():
    odd = "Qorvex-\ud800-lone"
    got = dec(odd, rules=[rule(odd)])
    assert got.format == odd
    with pytest.raises(ClassifyRulesError) as caught:
        dec(odd + "x", rules=[rule(odd)])
    assert "lone" not in str(caught.value)


def test_decide_refuses_a_non_level_with_fixed_text():
    with pytest.raises(ClassifyRulesError) as caught:
        rules_mod.decide(VlmAnswer("qorvex", None, 3), VALL, None, NSFW)  # type: ignore[arg-type]
    assert str(caught.value) == rules_mod._ERR_LEVEL


def test_the_cross_check_returns_a_flag_never_a_branch():
    # the branch is decided by the level alone, whatever the score says
    assert branch_for_level(NsfwLevel.safe, NsfwLevel.nudity) == "safe"
    assert check(NsfwLevel.safe, 0.99) is True
    assert branch_for_level(NsfwLevel.explicit, NsfwLevel.nudity) == "nsfw"
    assert check(NsfwLevel.explicit, 0.0) is True
