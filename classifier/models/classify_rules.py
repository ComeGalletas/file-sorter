"""The pure two-axis decision rules (CLS-002.1, CLS-002.D1).

Scores and category records in, a decision out: no model, no db, no file system, no logging.
Both the `classify` node and the calibration harness (CLS-003.1) import this module, so the eval
measures exactly what the gate measures. Thresholds and margins come from `ClassifyConfig`
(P-5); nothing here invents a value.

Errors are fixed text, raised from precomputed constants outside any `except` block, so
`__cause__` and `__context__` are None and no category name, score or rule value is quoted.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from classifier.config import AxisConfig, ClassifyConfig

Axis = Literal["format", "topic"]
Branch = Literal["safe", "nsfw"]

AXES: tuple[str, ...] = ("format", "topic")
RULE_BRANCHES: tuple[str, ...] = ("any", "safe", "nsfw")
UNSORTED = "unsorted"  # the fallback format (CLS-001.D2); never a candidate
TOP_N = 5  # CLS-002.D5
SCORE_DECIMALS = 4  # CLS-002.D5
# Scores and thresholds are floats: 0.60 - 0.55 is 0.04999..., which must still pass a 0.05
# margin (CLS-002.1, `>=`). Far below the 4-decimal precision of the stored scores.
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
_ERR_BRANCH = "invalid image branch"
_ERR_SCORE = "scores must be finite numbers"
_ERR_NSFW = "nsfw score and threshold must be finite numbers"


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
class Choice:
    """The decision for one image (CLS-002.D5 for the `*_top` lists)."""

    format: str = field(repr=False)
    topic: str | None = field(repr=False)
    needs_review: bool
    review_reason: str | None
    format_top: list[dict[str, object]] = field(repr=False)
    topic_top: list[dict[str, object]] = field(repr=False)


def _axis_config(axis: str, classify_config: ClassifyConfig) -> AxisConfig:
    return classify_config.format if axis == "format" else classify_config.topic


def nsfw_branch(score: float, threshold: float) -> Branch:
    """`nsfw` if the gate score reaches `nsfw.threshold`, else `safe` (R-CLS-1)."""
    if not (math.isfinite(score) and math.isfinite(threshold)):
        raise ClassifyRulesError(_ERR_NSFW)
    return "nsfw" if score >= threshold else "safe"


def _needs_default(rules: Sequence[CategoryRule], axis: str, classify_config: ClassifyConfig):
    """Raise when a rule of `axis` has no `min_score` and the axis has no default (D4)."""
    missing = _axis_config(axis, classify_config).default_min_score is None and any(
        rule.axis == axis and rule.min_score is None and rule.name != UNSORTED for rule in rules
    )
    if missing:
        raise ClassifyRulesError(_ERR_DEFAULT[axis])


def validate_rules(rules: Sequence[CategoryRule], classify_config: ClassifyConfig) -> None:
    """Check the whole rule set once, before any row changes (CLS-002.D4).

    Unknown axis or branch, duplicate names on an axis, a `parent_id` that is missing, on
    another axis or part of a loop, and a null `min_score` with a null axis default.
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
    for axis in AXES:
        _needs_default(rules, axis, classify_config)


def _threshold(rule: CategoryRule, axis_config: AxisConfig, axis: str) -> float:
    if rule.min_score is not None:
        return rule.min_score
    if axis_config.default_min_score is None:
        raise ClassifyRulesError(_ERR_DEFAULT[axis])
    return axis_config.default_min_score


def _rank(
    scores: Mapping[str, float], rules: Sequence[CategoryRule], exclude: str | None = None
) -> list[tuple[CategoryRule, float]]:
    """Candidates of one axis, best first: score descending, then name (CLS-002.D4)."""
    ranked = []
    for rule in rules:
        if rule.name == UNSORTED or rule.name == exclude or rule.name not in scores:
            continue
        score = float(scores[rule.name])
        if not math.isfinite(score):
            raise ClassifyRulesError(_ERR_SCORE)
        ranked.append((rule, score))
    ranked.sort(key=lambda item: (-item[1], item[0].name))
    return ranked


def _judge(
    winner: tuple[CategoryRule, float],
    others: Sequence[tuple[CategoryRule, float]],
    axis_config: AxisConfig,
    axis: str,
) -> bool:
    """R-CLS-3 / R-CLS-3a: clear `min_score`, and beat the best of `others` by the margin."""
    rule, score = winner
    if score + _EPS < _threshold(rule, axis_config, axis):
        return False
    return not others or score - others[0][1] + _EPS >= axis_config.margin


def _is_descendant(
    rule: CategoryRule, ancestor: CategoryRule, by_id: Mapping[int, CategoryRule]
) -> bool:
    """Whether `ancestor` is on `rule`'s `parent_id` chain (loop-safe; R-CLS-4)."""
    cursor = rule
    seen: set[int] = set()
    while cursor.parent_id is not None and cursor.id not in seen:
        seen.add(cursor.id)
        parent = by_id.get(cursor.parent_id)
        if parent is None:
            return False
        if parent.id == ancestor.id:
            return True
        cursor = parent
    return False


def _pick_axis(
    ranked: Sequence[tuple[CategoryRule, float]],
    axis_config: AxisConfig,
    axis: str,
    by_id: Mapping[int, CategoryRule] | None = None,
) -> CategoryRule | None:
    """The winner of one ranked axis, or None when nothing clears the rules.

    Nesting (R-CLS-4, CLS-002.D6): when the top two are ancestor and descendant, the margin is
    skipped and the deeper one wins if it clears its own `min_score`. If it does not, the
    ancestor is judged by the normal rule against the best category that is not its descendant.
    """
    if not ranked:
        return None
    if by_id is None:
        by_id = {rule.id: rule for rule, _ in ranked}
    if len(ranked) > 1:
        (top, _), (second, _) = ranked[0], ranked[1]
        if _is_descendant(second, top, by_id):
            deeper, ancestor = ranked[1], ranked[0]
        elif _is_descendant(top, second, by_id):
            deeper, ancestor = ranked[0], ranked[1]
        else:
            deeper = ancestor = None
        if deeper is not None and ancestor is not None:
            rule, score = deeper
            if score + _EPS >= _threshold(rule, axis_config, axis):
                return rule
            rest = [
                item
                for item in ranked
                if item[0].id != ancestor[0].id and not _is_descendant(item[0], ancestor[0], by_id)
            ]
            return ancestor[0] if _judge(ancestor, rest, axis_config, axis) else None
    return ranked[0][0] if _judge(ranked[0], ranked[1:], axis_config, axis) else None


def top_scores(ranked: Sequence[tuple[CategoryRule, float]]) -> list[dict[str, object]]:
    """The axis's top 5 as `[{"category", "score"}]`, 4 decimals (CLS-002.D5)."""
    return [
        {"category": rule.name, "score": round(score, SCORE_DECIMALS)}
        for rule, score in ranked[:TOP_N]
    ]


def _eligible(rule: CategoryRule, branch: str) -> bool:
    """R-CLS-6: `any` fits every image; `safe` and `nsfw` only their own branch."""
    return rule.branch == "any" or rule.branch == branch


def choose(
    format_scores: Mapping[str, float],
    topic_scores: Mapping[str, float],
    rules: Sequence[CategoryRule],
    branch: str,
    classify_config: ClassifyConfig,
) -> Choice:
    """Decide one image's format and topic from its two axes' scores.

    - Format (R-CLS-3): required. No winner, or a winner the image's `branch` excludes
      (R-CLS-6, CLS-002.D2), gives `unsorted` with `needs_review` and `review_reason = unsorted`.
    - Topic (R-CLS-3a): optional. No winner, or an ineligible winner, gives `None`; that is not
      a review case (CLS-001.D7). It is decided even when the format is `unsorted`.
    - Twin (R-CLS-3b, CLS-002.D3): the topic named like the chosen format is dropped from the
      topic candidates first. When the format is `unsorted`, nothing is dropped.
    - An ineligible winner never falls through to the runner-up.
    - `format_top` / `topic_top` are each axis's top 5 over its scored categories, before the
      twin is dropped (CLS-002.D5).

    A null `min_score` on a null axis default raises here too, as a backstop to the node's
    up-front `validate_rules` (CLS-002.D4).
    """
    if branch not in ("safe", "nsfw"):
        raise ClassifyRulesError(_ERR_BRANCH)
    for axis in AXES:
        _needs_default(rules, axis, classify_config)
    by_id = {rule.id: rule for rule in rules}
    format_rules = [rule for rule in rules if rule.axis == "format"]
    topic_rules = [rule for rule in rules if rule.axis == "topic"]

    format_ranked = _rank(format_scores, format_rules)
    format_winner = _pick_axis(format_ranked, classify_config.format, "format", by_id)
    if format_winner is not None and not _eligible(format_winner, branch):
        format_winner = None
    chosen_format = format_winner.name if format_winner is not None else UNSORTED

    topic_ranked = _rank(topic_scores, topic_rules)
    topic_candidates = _rank(topic_scores, topic_rules, exclude=chosen_format)
    topic_winner = _pick_axis(topic_candidates, classify_config.topic, "topic", by_id)
    if topic_winner is not None and not _eligible(topic_winner, branch):
        topic_winner = None

    unsorted = format_winner is None
    return Choice(
        format=chosen_format,
        topic=topic_winner.name if topic_winner is not None else None,
        needs_review=unsorted,
        review_reason=UNSORTED if unsorted else None,
        format_top=top_scores(format_ranked),
        topic_top=top_scores(topic_ranked),
    )
