"""The pure decision rules on the VLM path (CLS-002.D1, CLS-004.D1).

The VLM's answer and the category records in, a decision out: no model, no db, no file system,
no logging. Both the `classify` node and the calibration harness import this module, so the eval
measures exactly what the gate measures. The NSFW level threshold and the cross-check come from
`NsfwConfig` (P-5); nothing here invents a value. The SigLIP scoring rules (margins, ranking,
`choose`) were removed in CLS-006.1.

Errors are fixed text, raised from precomputed constants outside any `except` block, so
`__cause__` and `__context__` are None and no category name, score or rule value is quoted.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Literal

from classifier.config import AxisConfig, ClassifyConfig, CrossCheckConfig, NsfwConfig, NsfwLevel

Axis = Literal["format", "topic"]
Branch = Literal["safe", "nsfw"]

AXES: tuple[str, ...] = ("format", "topic")
RULE_BRANCHES: tuple[str, ...] = ("any", "safe", "nsfw")
UNSORTED = "unsorted"  # the fallback format (CLS-001.D2); never a candidate
# The cross-check compares float scores to its thresholds with `>=` / `<=`: a score a rounding
# error away from a threshold must still count as reaching it.
_EPS = 1e-9


class ClassifyRulesError(Exception):
    """The rules or the input are unusable. The message is fixed text with no value in it."""


_ERR_DEFAULT = {
    "format": "classify.format.default_min_score is null and a format has no min_score",
    "topic": "classify.topic.default_min_score is null and a topic has no min_score",
}
_ERR_AXIS = "category rule has an unknown axis"
_ERR_BRANCH_TAG = "category rule has an unknown branch"
_ERR_DUPLICATE = "duplicate category name on one axis"
_ERR_PARENT = "category parent is missing, on another axis, or loops"
_ERR_NSFW = "nsfw score and threshold must be finite numbers"
_ERR_UNKNOWN = "answer names a category that is not a rule of its axis"
_ERR_LEVEL = "nsfw level and min_level must be NsfwLevel values"


@dataclass(frozen=True)
class CategoryRule:
    """One `categories` row, reduced to what the decision needs."""

    id: int
    axis: str
    name: str = field(repr=False)
    folder: str = field(repr=False)
    min_score: float | None = field(repr=False)
    branch: str
    parent_id: int | None


@dataclass(frozen=True)
class VlmAnswer:
    """What the VLM said about one image (CLS-004.D1), as CLS-004.2 produces it.

    `format` is a format name, or `unsorted` for "none of these fits"; `topic` is a topic name,
    or None (the schema's `none`) for no topic.
    """

    format: str = field(repr=False)
    topic: str | None = field(repr=False)
    level: NsfwLevel
    # CLS-004.6: the effective prompt version(s) behind this answer; None when not recorded.
    prompt_version: str | None = None


@dataclass(frozen=True)
class VlmChoice:
    """The decision for one image on the VLM path (no scores, so no `*_top` lists)."""

    branch: Branch
    format: str = field(repr=False)
    topic: str | None = field(repr=False)
    needs_review: bool
    review_reason: str | None


def _axis_config(axis: str, classify_config: ClassifyConfig) -> AxisConfig:
    return classify_config.format if axis == "format" else classify_config.topic


def _needs_default(rules: Sequence[CategoryRule], axis: str, classify_config: ClassifyConfig):
    """Raise when a rule of `axis` has no `min_score` and the axis has no default (D4)."""
    missing = _axis_config(axis, classify_config).default_min_score is None and any(
        rule.axis == axis and rule.min_score is None and rule.name != UNSORTED for rule in rules
    )
    if missing:
        raise ClassifyRulesError(_ERR_DEFAULT[axis])


def branch_for_level(level: NsfwLevel, min_level: NsfwLevel) -> Branch:
    """`nsfw` if the VLM's level reaches `nsfw.min_level`, else `safe` (CLS-004.D3).

    The branch comes from the level alone: a category's own `branch` never changes it.
    """
    if not (isinstance(level, NsfwLevel) and isinstance(min_level, NsfwLevel)):
        raise ClassifyRulesError(_ERR_LEVEL)
    return "nsfw" if level >= min_level else "safe"


def nsfw_cross_check(
    level: NsfwLevel,
    min_level: NsfwLevel,
    nsfw_score: float | None,
    cross_check: CrossCheckConfig,
) -> bool:
    """Whether Falconsai strongly disagrees with the VLM's level (CLS-004.D5).

    True when the level is `safe` and the score is at or above `safe_above`, or the level is
    at or above `min_level` and the score is at or below `adult_below`. A null threshold turns
    its half off; no score (None) turns the check off. It only flags: the branch comes from
    the level alone (`branch_for_level`).
    """
    if not (isinstance(level, NsfwLevel) and isinstance(min_level, NsfwLevel)):
        raise ClassifyRulesError(_ERR_LEVEL)
    if nsfw_score is None:
        return False
    if not math.isfinite(nsfw_score):
        raise ClassifyRulesError(_ERR_NSFW)
    above, below = cross_check.safe_above, cross_check.adult_below
    if level == NsfwLevel.safe and above is not None and nsfw_score + _EPS >= above:
        return True
    return level >= min_level and below is not None and nsfw_score <= below + _EPS


def decide(
    answer: VlmAnswer,
    rules: Sequence[CategoryRule],
    nsfw_score: float | None,
    nsfw_config: NsfwConfig,
) -> VlmChoice:
    """Turn the VLM's answer into one image's branch, format and topic (CLS-004.D1, D3, D5).

    - Branch: from the level alone (`branch_for_level`). A category's `branch` never changes it.
    - Format (R-CLS-3): `unsorted` ("none fits"), or a format the branch excludes (R-CLS-6,
      CLS-002.D2), gives `unsorted`.
    - Topic (R-CLS-3a): `None`, an excluded topic, or the topic named like the chosen format
      (R-CLS-3b, CLS-002.D3) gives `None`. Decided even when the format is `unsorted`, where
      nothing is dropped. Not a review case (CLS-001.D7).
    - Review: `nsfw_disagreement` when the Falconsai cross-check flags (D5, CLS-004.D13); it
      wins over `unsorted`, which stays visible in `format`.
    - An ineligible answer never falls through to another category, and no score decides
      anything (D7).

    A format or topic that is not a rule of its axis raises: the node treats it as an
    unanswered call (CLS-004.D4).
    """
    branch = branch_for_level(answer.level, nsfw_config.min_level)
    flagged = nsfw_cross_check(
        answer.level, nsfw_config.min_level, nsfw_score, nsfw_config.cross_check
    )
    named = {(rule.axis, rule.name): rule for rule in rules if rule.name != UNSORTED}

    format_rule = None
    if answer.format != UNSORTED:
        format_rule = named.get(("format", answer.format))
        if format_rule is None:
            raise ClassifyRulesError(_ERR_UNKNOWN)
        if not _eligible(format_rule, branch):
            format_rule = None
    chosen_format = format_rule.name if format_rule is not None else UNSORTED

    topic_rule = None
    if answer.topic is not None:
        topic_rule = named.get(("topic", answer.topic))
        if topic_rule is None:
            raise ClassifyRulesError(_ERR_UNKNOWN)
        if not _eligible(topic_rule, branch) or topic_rule.name == chosen_format:
            topic_rule = None

    unsorted = format_rule is None
    reason = "nsfw_disagreement" if flagged else (UNSORTED if unsorted else None)
    return VlmChoice(
        branch=branch,
        format=chosen_format,
        topic=topic_rule.name if topic_rule is not None else None,
        needs_review=reason is not None,
        review_reason=reason,
    )


def validate_rules(
    rules: Sequence[CategoryRule], classify_config: ClassifyConfig | None = None
) -> None:
    """Check the whole rule set once, before any row changes (CLS-002.D4).

    Unknown axis or branch, duplicate names on an axis, a `parent_id` that is missing, on
    another axis or part of a loop, and a null `min_score` with a null axis default. On the
    VLM path there is no `classify_config` and no score to compare, so the last check is
    skipped (CLS-004.D7).
    """
    problem = None
    seen: set[tuple[str, str]] = set()
    by_id = {rule.id: rule for rule in rules}
    for rule in rules:
        if rule.axis not in AXES:
            problem = problem or _ERR_AXIS
        if rule.branch not in RULE_BRANCHES:
            problem = problem or _ERR_BRANCH_TAG
        key = (rule.axis, rule.name)
        if key in seen:
            problem = problem or _ERR_DUPLICATE
        seen.add(key)
        hops = 0
        cursor = rule
        while cursor.parent_id is not None:
            parent = by_id.get(cursor.parent_id)
            hops += 1
            if parent is None or parent.axis != rule.axis or hops > len(rules):
                problem = problem or _ERR_PARENT
                break
            cursor = parent
    if problem is not None:
        raise ClassifyRulesError(problem)
    if classify_config is not None:
        for axis in AXES:
            _needs_default(rules, axis, classify_config)


def _eligible(rule: CategoryRule, branch: str) -> bool:
    """R-CLS-6: `any` fits every image; `safe` and `nsfw` only their own branch."""
    return rule.branch == "any" or rule.branch == branch
