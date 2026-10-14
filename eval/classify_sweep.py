"""The threshold sweep behind the calibration (CLS-003.1; R-CLS-8, CLS-001.D5, CLS-003.D1-D3).

Pure: scored, labelled items in, proposed values and measures out. No model, db, file system
or logging. Every decision goes through `classifier.models.classify_rules` (`choose`,
`nsfw_branch`), the same rules the `classify` node and gate 3 run (CLS-002.D1).

The labels are the human's private data (TST-008.D1): every field that holds a label, a score
or a category name is `repr=False`, and errors are fixed text. Counts live in `Metrics` only
so the caller can turn them into the public form; nothing here prints.
"""

import random
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

from classifier.config import AxisConfig, ClassifyConfig
from classifier.models.classify_rules import UNSORTED, CategoryRule, choose, nsfw_branch

SEED = 20261014  # pinned (CLS-003.1): the same folds on every run
FOLDS = 5
GAP_POINTS = 5.0  # CLS-003.D3: a bigger fitted/held-out gap is DONE_WITH_CONCERNS
COARSE_STEP = 0.02
FINE_STEP = 0.005
FINE_SPAN = 4  # fine steps either side of the coarse pick
SLACK_POINTS = 1.0  # CLS-003.1: how much agreement the sweep gives up for a safer threshold
UNRECOGNIZED_LIMIT_PCT = 10.0  # CLS-001.D5
MARGIN_MAX = 0.30
_DUMMY = AxisConfig(default_min_score=0.5, margin=0.0)  # an axis the sweep does not look at


class SweepError(Exception):
    """The sweep input is unusable. The message is fixed text with no value in it."""


_ERR_EMPTY = "the sweep has no gate rows to fit"
_ERR_AXIS = "unknown axis"


@dataclass(frozen=True)
class Item:
    """One scored, labelled image. Every field is private data (TST-008.D1)."""

    format_scores: Mapping[str, float] = field(repr=False)
    topic_scores: Mapping[str, float] = field(repr=False)
    nsfw: float = field(repr=False)
    format: str | None = field(repr=False)
    topic: str | None = field(repr=False)
    adult: bool = field(repr=False)
    suggestive_negative: bool = field(repr=False)
    calibration_only: bool = field(repr=False)


@dataclass(frozen=True)
class AxisFit:
    """One axis's proposed values: config values, not data about the images."""

    default_min_score: float = field(repr=False)
    margin: float = field(repr=False)
    overrides: tuple[tuple[str, float], ...] = field(repr=False, default=())  # sorted by name


@dataclass(frozen=True)
class Metrics:
    """The CLS-001.D5 measures over gate rows, as raw counts (TST-008.D4)."""

    format_correct: int = field(repr=False, default=0)
    format_total: int = field(repr=False, default=0)
    topic_correct: int = field(repr=False, default=0)
    topic_total: int = field(repr=False, default=0)
    unsorted: int = field(repr=False, default=0)
    rows: int = field(repr=False, default=0)
    adult_ok: bool = field(repr=False, default=True)
    suggestive_ok: bool = field(repr=False, default=True)

    def __add__(self, other: "Metrics") -> "Metrics":
        return Metrics(
            self.format_correct + other.format_correct,
            self.format_total + other.format_total,
            self.topic_correct + other.topic_correct,
            self.topic_total + other.topic_total,
            self.unsorted + other.unsorted,
            self.rows + other.rows,
            self.adult_ok and other.adult_ok,
            self.suggestive_ok and other.suggestive_ok,
        )


@dataclass(frozen=True)
class Calibration:
    """The result: the proposal, the fitted and held-out measures, and the check verdicts."""

    feasible: bool = field(repr=False)  # False: no `nsfw.threshold` satisfies the NSFW rows
    nsfw_threshold: float = field(repr=False)
    format: AxisFit = field(repr=False)
    topic: AxisFit = field(repr=False)
    fitted: Metrics = field(repr=False)
    held_out: Metrics = field(repr=False)
    format_overrides_survive: bool | None = field(repr=False)  # None: none were proposed
    topic_overrides_survive: bool | None = field(repr=False)


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def gap_points(fitted: Metrics, held_out: Metrics) -> tuple[float, float]:
    """Fitted minus held-out agreement, in points, for format and topic (CLS-003.D3)."""
    return (
        _pct(fitted.format_correct, fitted.format_total)
        - _pct(held_out.format_correct, held_out.format_total),
        _pct(fitted.topic_correct, fitted.topic_total)
        - _pct(held_out.topic_correct, held_out.topic_total),
    )


def has_concerns(fitted: Metrics, held_out: Metrics) -> bool:
    return any(gap > GAP_POINTS for gap in gap_points(fitted, held_out))


# --- Rules and config for a candidate ------------------------------------------------------


def _config(base: ClassifyConfig, fmt: AxisConfig, topic: AxisConfig) -> ClassifyConfig:
    return base.model_copy(update={"format": fmt, "topic": topic})


def _axis_config(fit: AxisFit) -> AxisConfig:
    return AxisConfig(default_min_score=fit.default_min_score, margin=fit.margin)


def _with_overrides(rules: Sequence[CategoryRule], axis: str, overrides: Mapping[str, float]):
    return [
        replace(rule, min_score=overrides[rule.name])
        if rule.axis == axis and rule.name in overrides
        else rule
        for rule in rules
    ]


def materialize(
    rules: Sequence[CategoryRule],
    base: ClassifyConfig,
    fmt: AxisFit,
    topic: AxisFit,
) -> tuple[list[CategoryRule], ClassifyConfig]:
    """The rules (with the overrides applied) and the config a proposal stands for."""
    applied = _with_overrides(rules, "format", dict(fmt.overrides))
    applied = _with_overrides(applied, "topic", dict(topic.overrides))
    return applied, _config(base, _axis_config(fmt), _axis_config(topic))


# --- Measures -------------------------------------------------------------------------------


def gate_items(items: Sequence[Item]) -> list[Item]:
    """The rows every measure counts: those not tagged calibration-only (TST-008.D2)."""
    return [item for item in items if not item.calibration_only]


def measure(
    items: Sequence[Item],
    rules: Sequence[CategoryRule],
    config: ClassifyConfig,
    threshold: float,
) -> Metrics:
    """The CLS-001.D5 measures over the gate rows among `items` (TST-008.D4)."""
    out = Metrics()
    for item in gate_items(items):
        branch = nsfw_branch(item.nsfw, threshold)
        choice = choose(item.format_scores, item.topic_scores, rules, branch, config)
        flagged = branch == "nsfw"
        out = out + Metrics(
            format_correct=int(item.format is not None and choice.format == item.format),
            format_total=int(item.format is not None),
            topic_correct=int(item.topic is not None and choice.topic == item.topic),
            topic_total=int(item.topic is not None),
            unsorted=int(choice.format == UNSORTED),
            rows=1,
            adult_ok=flagged == item.adult,
            suggestive_ok=not (item.suggestive_negative and flagged),
        )
    return out


# --- NSFW threshold ----------------------------------------------------------------------


def fit_nsfw(items: Sequence[Item]) -> float | None:
    """The middle of the feasible interval, or None when it is empty (the lead's rule).

    Feasible: every adult row scores `>=` the threshold and every other row scores below it,
    over all rows including the calibration-only ones (TST-008.D2). The constraint is never
    relaxed. The returned value is rounded as far as it stays feasible.
    """
    safe = [item.nsfw for item in items if not item.adult]
    adult = [item.nsfw for item in items if item.adult]
    low = max(safe) if safe else 0.0
    high = min(adult) if adult else 1.0
    if not low < high:
        return None
    middle = (low + high) / 2
    for places in (3, 4, 6):
        value = round(middle, places)
        if low < value <= high:
            return value
    return middle


def _best_effort_nsfw(items: Sequence[Item], near: float) -> float:
    """When no threshold is feasible: the fewest misclassified rows, ties nearest `near`."""
    scores = sorted({item.nsfw for item in items} | {0.0, 1.0})
    candidates = [(a + b) / 2 for a, b in zip(scores, scores[1:], strict=False)] + [scores[-1]]

    def errors(threshold: float) -> int:
        return sum((item.nsfw >= threshold) != item.adult for item in items)

    return min(candidates, key=lambda t: (errors(t), abs(t - near)))


# --- Grid search on one axis -----------------------------------------------------------------


def _frange(start: float, stop: float, step: float) -> list[float]:
    count = int(round((stop - start) / step)) + 1
    return [round(start + i * step, 4) for i in range(max(count, 1))]


def _axis_max(items: Sequence[Item], axis: str) -> float:
    if axis not in ("format", "topic"):
        raise SweepError(_ERR_AXIS)
    top = [
        max(scores.values(), default=0.0)
        for item in items
        for scores in [item.format_scores if axis == "format" else item.topic_scores]
    ]
    return max(top, default=1.0)


def sweep_axis(
    items: Sequence[Item],
    rules: Sequence[CategoryRule],
    base: ClassifyConfig,
    threshold: float,
    axis: str,
    fixed_format: AxisFit | None = None,
    slack_points: float = SLACK_POINTS,
) -> AxisFit:
    """Fit `default_min_score` and `margin` for one axis on the gate rows (R-CLS-8).

    Agreement alone only improves as the thresholds fall (a lower bar never turns a hit into a
    miss), so the best agreement sits at 0 and would switch the review fallback off. The fit
    therefore takes the most conservative values that stay within `slack_points` of the best
    agreement: the highest `default_min_score`, with the median `margin` that allows it. On the
    format axis the unrecognized share must also stay under the gate's 10% when the best does
    (CLS-001.D5).

    Format is swept alone. Topic is swept given the fitted format, because the twin is dropped
    from the topic candidates (R-CLS-3b). A coarse grid first, then a fine grid around its pick.
    """
    rows = gate_items(items)
    if not rows:
        raise SweepError(_ERR_EMPTY)
    if axis == "topic" and fixed_format is None:
        raise SweepError(_ERR_AXIS)
    top = min(_axis_max(rows, axis) + COARSE_STEP, 1.0 if base.score == "sigmoid" else 2.0)
    if axis == "format":
        use = [replace(r, topic_scores={}) for r in rows]
        rule_set: Sequence[CategoryRule] = rules
    else:
        assert fixed_format is not None
        use = rows
        rule_set = materialize(rules, base, fixed_format, AxisFit(0.0, 0.0))[0]

    def key(min_score: float, margin: float) -> tuple[int, int]:
        axis_config = AxisConfig(default_min_score=min_score, margin=margin)
        if axis == "format":
            config = _config(base, axis_config, _DUMMY)
        else:
            assert fixed_format is not None
            config = _config(base, _axis_config(fixed_format), axis_config)
        metrics = measure(use, rule_set, config, threshold)
        right = metrics.format_correct if axis == "format" else metrics.topic_correct
        return (right, metrics.unsorted)

    total = sum(1 for r in rows if (r.format if axis == "format" else r.topic) is not None)
    allowed_misses = int(total * slack_points / 100.0)
    limit = int(len(rows) * UNRECOGNIZED_LIMIT_PCT / 100.0 - 1e-9)  # strictly under the limit

    def pick(scored: Mapping[tuple[float, float], tuple[int, int]]) -> tuple[float, float]:
        best_right = max(right for right, _ in scored.values())
        best_unsorted = min(u for right, u in scored.values() if right == best_right)
        under = axis == "format" and best_unsorted <= limit
        keep = [
            c
            for c, (right, unsorted) in scored.items()
            if right >= best_right - allowed_misses and (not under or unsorted <= limit)
        ]
        pool = keep or list(scored)
        highest = max(m for m, _ in pool)
        margins = sorted(g for m, g in pool if m == highest)
        return (highest, margins[(len(margins) - 1) // 2])  # the lower median margin

    coarse = [
        (m, g)
        for m in _frange(COARSE_STEP, top, COARSE_STEP)
        for g in _frange(0.0, MARGIN_MAX, COARSE_STEP)
    ]
    scored = {c: key(*c) for c in coarse}
    centre = pick(scored)
    span = FINE_SPAN * FINE_STEP
    for m in _frange(max(centre[0] - span, FINE_STEP), centre[0] + span, FINE_STEP):
        for g in _frange(max(centre[1] - span, 0.0), centre[1] + span, FINE_STEP):
            scored.setdefault((m, g), key(m, g))
    minimum, margin = pick(scored)
    return AxisFit(round(minimum, 4), round(margin, 4))


# --- Per-category overrides -----------------------------------------------------------------


def _top_three(items: Sequence[Item], axis: str, names: set[str]) -> dict[str, list[int]]:
    """Per category, the items where it ranks in the top 3 of its axis.

    A category's `min_score` can only change a decision where the category is the winner or
    the deeper half of the nested top pair (CLS-002.D6), and the twin drop (R-CLS-3b) takes
    one category out of a topic ranking, so rank <= 3 is a safe superset.
    """
    where: dict[str, list[int]] = defaultdict(list)
    for index, item in enumerate(items):
        scores = item.format_scores if axis == "format" else item.topic_scores
        ranked = sorted((name for name in scores if name in names), key=lambda n: (-scores[n], n))
        for name in ranked[:3]:
            where[name].append(index)
    return where


def fit_overrides(
    items: Sequence[Item],
    rules: Sequence[CategoryRule],
    base: ClassifyConfig,
    threshold: float,
    axis: str,
    fit: AxisFit,
    fixed_format: AxisFit | None = None,
) -> AxisFit:
    """Add per-category `min_score` overrides where they raise agreement by a whole row.

    Coordinate ascent in name order, at most three passes. A candidate is taken only when it
    gains at least one more correctly decided row than the current value (CLS-003.1: no
    override on noise). Only the rows where the category ranks in the top 3 are re-decided.
    """
    rows = gate_items(items)
    names = sorted(r.name for r in rules if r.axis == axis and r.name != UNSORTED)
    where = _top_three(rows, axis, set(names))
    top = min(_axis_max(rows, axis) + COARSE_STEP, 1.0 if base.score == "sigmoid" else 2.0)
    grid = _frange(COARSE_STEP, top, COARSE_STEP)
    current = dict(fit.overrides)

    def correct(subset: list[Item], overrides: Mapping[str, float]) -> int:
        if axis == "format":
            trial = replace(fit, overrides=tuple(overrides.items()))
            applied, config = materialize(rules, base, trial, AxisFit(0.0, 0.0))
            config = _config(base, config.format, _DUMMY)
            use = [replace(r, topic_scores={}) for r in subset]
            return measure(use, applied, config, threshold).format_correct
        assert fixed_format is not None
        applied, config = materialize(
            rules, base, fixed_format, replace(fit, overrides=tuple(overrides.items()))
        )
        return measure(subset, applied, config, threshold).topic_correct

    for _ in range(3):
        changed = False
        for name in names:
            indexes = where.get(name, [])
            if not indexes:
                continue
            subset = [rows[i] for i in indexes]
            held = correct(subset, current)
            best_value: float | None = None
            best_gain = 0
            for value in grid:
                same = current.get(name, fit.default_min_score)
                if value == same:
                    continue
                gain = correct(subset, {**current, name: value}) - held
                if gain >= best_gain and gain >= 1:  # the highest value among the best gains
                    best_gain, best_value = gain, value
            if best_value is not None and best_gain >= 1:
                current[name] = best_value
                changed = True
        if not changed:
            break
    return replace(fit, overrides=tuple(sorted(current.items())))


# --- Cross-validation and the whole calibration ---------------------------------------------


def _folds(items: Sequence[Item], seed: int) -> list[list[int]]:
    order = list(range(len(items)))
    random.Random(seed).shuffle(order)
    return [order[k::FOLDS] for k in range(FOLDS)]


def _fit_threshold(items: Sequence[Item], fallback: float) -> float:
    fitted = fit_nsfw(items)
    return fitted if fitted is not None else fallback


def calibrate(
    items: Sequence[Item],
    rules: Sequence[CategoryRule],
    base: ClassifyConfig,
    seed: int = SEED,
    slack_points: float = SLACK_POINTS,
) -> Calibration:
    """Fit on every labelled row, check on 5 held-out folds, decide the overrides (CLS-003.D3).

    NSFW comes first because the branch gates category eligibility (R-CLS-6). If it has no
    feasible threshold the result says so and carries no category proposal. Overrides stay in
    the proposal only if the pooled held-out agreement of their axis does not drop with them
    (the lead's rule on #101).
    """
    if not gate_items(items):
        raise SweepError(_ERR_EMPTY)
    threshold = fit_nsfw(items)
    zero = AxisFit(0.0, 0.0)
    if threshold is None:
        best = _best_effort_nsfw(items, base_nsfw_near(items))
        applied, config = materialize(rules, base, zero, zero)
        shown = measure(items, applied, config, best)
        failed = replace(shown, adult_ok=False)
        return Calibration(False, best, zero, zero, failed, failed, None, None)

    # Pass 1: format, per fold, with and without overrides.
    folds = _folds(items, seed)
    plain = with_ov = Metrics()
    fold_fits: list[tuple[list[Item], list[Item], float, AxisFit, AxisFit]] = []
    for held in folds:
        held_set = set(held)
        test = [items[i] for i in held]
        train = [item for i, item in enumerate(items) if i not in held_set]
        if not gate_items(train) or not test:
            continue
        thr = _fit_threshold(train, threshold)
        base_fit = sweep_axis(train, rules, base, thr, "format", slack_points=slack_points)
        ov_fit = fit_overrides(train, rules, base, thr, "format", base_fit)
        fold_fits.append((train, test, thr, base_fit, ov_fit))
        for fit, bucket in ((base_fit, "plain"), (ov_fit, "ov")):
            applied, config = materialize(rules, base, fit, zero)
            config = _config(base, config.format, _DUMMY)
            part = measure(test, applied, config, thr)
            if bucket == "plain":
                plain = plain + part
            else:
                with_ov = with_ov + part
    full_format = sweep_axis(items, rules, base, threshold, "format", slack_points=slack_points)
    full_format_ov = fit_overrides(items, rules, base, threshold, "format", full_format)
    format_has_ov = bool(full_format_ov.overrides)
    keep_format = format_has_ov and with_ov.format_correct >= plain.format_correct
    chosen_format = full_format_ov if keep_format else full_format
    format_survive = (with_ov.format_correct >= plain.format_correct) if format_has_ov else None

    # Pass 2: topic, given each fold's chosen format.
    topic_plain = topic_ov = Metrics()
    for train, test, thr, base_fit, ov_fit in fold_fits:
        fold_format = ov_fit if keep_format else base_fit
        topic_base = sweep_axis(train, rules, base, thr, "topic", fold_format, slack_points)
        topic_with = fit_overrides(train, rules, base, thr, "topic", topic_base, fold_format)
        for fit, bucket in ((topic_base, "plain"), (topic_with, "ov")):
            applied, config = materialize(rules, base, fold_format, fit)
            part = measure(test, applied, config, thr)
            if bucket == "plain":
                topic_plain = topic_plain + part
            else:
                topic_ov = topic_ov + part
    full_topic = sweep_axis(items, rules, base, threshold, "topic", chosen_format, slack_points)
    full_topic_ov = fit_overrides(items, rules, base, threshold, "topic", full_topic, chosen_format)
    topic_has_ov = bool(full_topic_ov.overrides)
    keep_topic = topic_has_ov and topic_ov.topic_correct >= topic_plain.topic_correct
    chosen_topic = full_topic_ov if keep_topic else full_topic
    topic_survive = (topic_ov.topic_correct >= topic_plain.topic_correct) if topic_has_ov else None

    held_out = topic_ov if keep_topic else topic_plain
    held_out = replace(
        held_out,
        format_correct=(with_ov if keep_format else plain).format_correct,
        format_total=plain.format_total,
        unsorted=(with_ov if keep_format else plain).unsorted,
        adult_ok=plain.adult_ok and with_ov.adult_ok,
        suggestive_ok=plain.suggestive_ok and with_ov.suggestive_ok,
    )
    applied, config = materialize(rules, base, chosen_format, chosen_topic)
    fitted = measure(items, applied, config, threshold)
    return Calibration(
        True,
        threshold,
        chosen_format,
        chosen_topic,
        fitted,
        held_out,
        format_survive,
        topic_survive,
    )


def base_nsfw_near(items: Sequence[Item]) -> float:
    """A neutral tie-break target for the infeasible case: the middle of the score range."""
    scores = [item.nsfw for item in items]
    return (min(scores) + max(scores)) / 2 if scores else 0.5


def per_category(
    items: Sequence[Item],
    rules: Sequence[CategoryRule],
    config: ClassifyConfig,
    threshold: float,
) -> dict[str, dict[str, tuple[int, int]]]:
    """`--detail` only: per axis and label, (correct, total). Console only, never pasted."""
    out: dict[str, dict[str, tuple[int, int]]] = {"format": {}, "topic": {}}
    for item in gate_items(items):
        choice = choose(
            item.format_scores, item.topic_scores, rules, nsfw_branch(item.nsfw, threshold), config
        )
        for axis, label, got in (
            ("format", item.format, choice.format),
            ("topic", item.topic, choice.topic),
        ):
            if label is None:
                continue
            right, total = out[axis].get(label, (0, 0))
            out[axis][label] = (right + int(got == label), total + 1)
    return out
