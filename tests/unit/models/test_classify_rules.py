"""The VLM-path decision rules (CLS-002.1, CLS-004): pure, artificial category names."""

import ast
from pathlib import Path

import pytest

from classifier.config import AxisConfig, ClassifyConfig, CrossCheckConfig, NsfwConfig, NsfwLevel
from classifier.models import classify_rules as rules_mod
from classifier.models.classify_rules import (
    CategoryRule,
    ClassifyRulesError,
    VlmAnswer,
    branch_for_level,
    nsfw_cross_check,
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
    answer = VlmAnswer(SECRET_NAME, "Vrelk-Planted-Topic", NsfwLevel.safe)
    got = rules_mod.decide(answer, [planted, topic], 0.97654321, NSFW)
    assert got.format == SECRET_NAME and got.topic == "Vrelk-Planted-Topic"
    for text in (repr(planted), str(planted), repr(answer), str(answer), repr(got), str(got)):
        for secret in (SECRET_NAME, SECRET_FOLDER, "Vrelk-Planted-Topic", "0.3141", "0.9765"):
            assert secret not in text


@pytest.mark.parametrize(
    "call",
    [
        lambda: validate_rules([rule(SECRET_NAME, branch="adult")], cfg()),
        lambda: validate_rules([rule(SECRET_NAME, axis="colour")], cfg()),
        lambda: validate_rules([rule(SECRET_NAME), rule(SECRET_NAME)], cfg()),
        lambda: validate_rules([rule(SECRET_NAME, parent_id=404)], cfg()),
        lambda: validate_rules([rule(SECRET_NAME)], cfg(fmt_default=None)),
        lambda: rules_mod.decide(
            VlmAnswer(SECRET_NAME, None, NsfwLevel.safe), [rule(SECRET_NAME)], float("nan"), NSFW
        ),
        lambda: rules_mod.decide(
            VlmAnswer(SECRET_NAME, None, "adult"),  # type: ignore[arg-type]
            [rule(SECRET_NAME)],
            None,
            NSFW,
        ),
        lambda: rules_mod.decide(
            VlmAnswer(SECRET_NAME, None, NsfwLevel.safe), [rule("zhyndel")], None, NSFW
        ),
        lambda: rules_mod.decide(
            VlmAnswer("zhyndel", SECRET_NAME, NsfwLevel.safe), [rule("zhyndel")], None, NSFW
        ),
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
    got = rules_mod.decide(VlmAnswer(odd, None, NsfwLevel.safe), rules, None, NSFW)
    assert got.format == odd
    with pytest.raises(ClassifyRulesError) as caught:
        validate_rules([rule(odd), rule(odd)], cfg())
    assert "\ud800" not in str(caught.value)
    with pytest.raises(ClassifyRulesError) as unknown:
        rules_mod.decide(VlmAnswer(odd, None, NsfwLevel.safe), [rule("zhyndel")], None, NSFW)
    assert "\ud800" not in str(unknown.value)


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
