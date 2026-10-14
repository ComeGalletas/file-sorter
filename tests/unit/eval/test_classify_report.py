"""The report and the entry point of the calibration harness (CLS-003.1.3; TST-008.D1, D6).

The default output must be pasteable: verdicts, whole percents, and config values only.
"""

import re
import sys
from pathlib import Path

EVAL = Path(__file__).resolve().parents[3] / "eval"
SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
for folder in (EVAL, SCRIPTS):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import classify_eval as ev  # noqa: E402
import classify_sweep as sweep  # noqa: E402
from classify_sweep import AxisFit, Calibration, Metrics  # noqa: E402

ROWS = 777


def calibration(**changes) -> Calibration:
    fitted = Metrics(
        format_correct=725,
        format_total=ROWS,
        topic_correct=600,
        topic_total=700,
        unsorted=31,
        rows=ROWS,
    )
    base = dict(
        feasible=True,
        nsfw_threshold=0.52,
        format=AxisFit(0.31, 0.04, (("Vlarn", 0.2),)),
        topic=AxisFit(0.28, 0.03, (("Blip", 0.15), ("Aqzel", 0.1))),
        fitted=fitted,
        held_out=Metrics(
            format_correct=715,
            format_total=ROWS,
            topic_correct=590,
            topic_total=700,
            unsorted=33,
            rows=ROWS,
        ),
        format_overrides_survive=True,
        topic_overrides_survive=True,
    )
    return Calibration(**(base | changes))


def test_the_public_form_has_verdicts_whole_percents_and_the_proposed_values():
    text = "\n".join(ev.render(calibration(), 1.0))
    assert "format agreement: PASS 93% (gate >= 90%)" in text  # 725/777 = 93.3, rounded down
    assert "topic agreement: PASS 85% (gate >= 85%)" in text  # 600/700 = 85.7
    assert "unrecognized format: PASS 3% (gate < 10%)" in text
    assert "adult flagged and the rest safe: ok" in text
    assert "suggestive-negative safe: ok" in text
    assert "classify.format.default_min_score: 0.31" in text
    assert "nsfw.threshold: 0.52" in text
    assert "fitted vs held-out gap <= 5 points: ok" in text


def test_percentages_round_down_never_up():
    held = Metrics(format_correct=929, format_total=1000, topic_total=0, rows=1000)
    text = "\n".join(ev.render(calibration(held_out=held), 1.0))
    assert "held-out (5-fold, seed 20261014): format 92%" in text


def test_the_default_output_has_no_count_no_decimal_percent_and_no_detail():
    text = "\n".join(ev.render(calibration(), 1.0))
    assert str(ROWS) not in text and "700" not in text and "725" not in text
    assert not re.search(r"\d+\.\d+%", text)
    assert "DETAIL" not in text


def test_adult_and_suggestive_negative_print_a_verdict_only():
    fitted = Metrics(format_total=10, topic_total=10, rows=10, adult_ok=False, suggestive_ok=False)
    text = "\n".join(ev.render(calibration(fitted=fitted), 1.0))
    assert "adult flagged and the rest safe: FAIL" in text
    assert "suggestive-negative safe: FAIL" in text
    assert "adult" not in text.replace("adult flagged and the rest safe", "").replace(
        "adult ok", ""
    ).replace("adult FAIL", "")


def test_a_failing_criterion_says_fail():
    low = Metrics(format_correct=100, format_total=ROWS, topic_total=1, rows=ROWS, unsorted=300)
    text = "\n".join(ev.render(calibration(fitted=low), 1.0))
    assert "format agreement: FAIL 12%" in text
    assert "unrecognized format: FAIL 38%" in text


def test_a_gap_over_five_points_prints_concerns():
    far = Metrics(
        format_correct=500, format_total=ROWS, topic_correct=600, topic_total=700, rows=ROWS
    )
    assert "gap <= 5 points: CONCERNS" in "\n".join(ev.render(calibration(held_out=far), 1.0))


def test_overrides_are_listed_by_axis_then_name_and_nothing_else_about_them():
    text = ev.render(calibration(), 1.0)
    start = next(i for i, line in enumerate(text) if "min_score overrides" in line)
    assert text[start + 1 :] == [
        "    format Vlarn: 0.2",
        "    topic Aqzel: 0.1",
        "    topic Blip: 0.15",
    ]


def test_overrides_that_fail_the_held_out_check_are_reported_as_dropped():
    text = "\n".join(
        ev.render(
            calibration(
                format=AxisFit(0.31, 0.04),
                topic=AxisFit(0.28, 0.03),
                format_overrides_survive=False,
                topic_overrides_survive=None,
            ),
            1.0,
        )
    )
    assert "format dropped (held-out agreement fell), topic none proposed" in text
    assert "min_score overrides (migration 0004): none" in text


def test_an_infeasible_nsfw_threshold_stops_with_verdicts_only():
    fitted = Metrics(rows=3, adult_ok=False, suggestive_ok=True)
    zero = AxisFit(0.0, 0.0)
    result = Calibration(False, 0.5, zero, zero, fitted, fitted, None, None)
    assert ev.render(result, 1.0)[1:] == [
        "adult flagged and the rest safe: FAIL",
        "suggestive-negative safe: ok",
        "no nsfw.threshold satisfies every labelled NSFW row: nothing else was swept",
    ]


def test_detail_adds_one_decimal_figures_and_the_lines_it_is_given():
    lines = ev.render(calibration(), 1.0, ["  format Qorvex: 90.0% (9/10)"])
    text = "\n".join(lines)
    assert "DETAIL (box console only: never paste, commit or post)" in text
    assert "fitted: format 93.3%" in text
    assert "format Qorvex: 90.0% (9/10)" in text


def test_the_tenth_helper_and_empty_totals():
    assert ev._tenth(1, 3) == "33.3%" and ev._floor(1, 3) == "33%"
    assert ev._tenth(0, 0) == "n/a" and ev._floor(0, 0) == "n/a"


# --- The entry point --------------------------------------------------------------------


def test_main_without_a_dsn_fails_with_fixed_text(monkeypatch, capsys):
    monkeypatch.delenv("DB_DSN", raising=False)
    assert ev.main([]) == 1
    assert "DB_DSN is not set" in capsys.readouterr().err


def test_main_prints_the_type_only_for_an_unexpected_error(monkeypatch, capsys):
    monkeypatch.setenv("DB_DSN", "postgresql://user:hunter2@host/db")

    def boom(*args, **kwargs):
        raise ValueError("/source/Planted Name/secret.png hunter2")

    monkeypatch.setattr(ev, "run_eval", boom)
    assert ev.main([]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "classify_eval FAIL: run errored (ValueError)"


def test_main_prints_an_eval_error_as_its_fixed_text(monkeypatch, capsys):
    monkeypatch.setenv("DB_DSN", "postgresql://x/y")

    def fail(*args, **kwargs):
        raise ev.EvalError("the labels and the images do not match exactly")

    monkeypatch.setattr(ev, "run_eval", fail)
    assert ev.main([]) == 1
    assert "do not match exactly" in capsys.readouterr().err


def test_main_prints_the_report_and_passes_the_flags(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DB_DSN", "postgresql://x/y")
    seen = {}

    def fake(dsn, images, labels, cache, detail, slack, backend=None):
        seen.update(cache=cache, detail=detail, slack=slack)
        return ["line one", "line two"]

    monkeypatch.setattr(ev, "run_eval", fake)
    assert ev.main(["--detail", "--slack-points", "2", "--cache-dir", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "line one\nline two\n"
    assert seen == {"cache": tmp_path, "detail": True, "slack": 2.0}
    ev.main(["--no-cache"])
    assert seen["cache"] is None


def test_a_sweep_error_is_reported_as_fixed_text(monkeypatch, capsys):
    monkeypatch.setenv("DB_DSN", "postgresql://x/y")

    def empty(*args, **kwargs):
        raise sweep.SweepError("the sweep has no gate rows to fit")

    monkeypatch.setattr(ev, "run_eval", empty)
    assert ev.main([]) == 1
    assert "no gate rows" in capsys.readouterr().err


def test_defaults_point_inside_the_repo():
    assert str(ev.REPO) in str(ev.IMAGES) and str(ev.REPO) in str(ev.LABELS)
