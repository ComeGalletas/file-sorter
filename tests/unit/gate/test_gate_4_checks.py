"""TST-015.1: gate 4's pure checks, on synthetic rows and synthetic bodies (no db, no app).

The runner against a migrated test database is tests/db/gate/test_gate_4_runner.py. The real
ledger only runs at `make gate-4`, at G1 (the human's).
"""

import dataclasses
import hashlib
import importlib.util
from pathlib import Path

import pytest

from classifier.api.views import ADULT_BRANCH, is_adult

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_4.py"
_spec = importlib.util.spec_from_file_location("gate_4_checks", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_4)

Code = gate_4.Code
PLANT_DIR = "Qorvex-Zhyndel-Plant"
PLANT_STEM = "Zhyndel-Vruthmar-Raw"
PLANT_PATH = f"/source/{PLANT_DIR}/{PLANT_STEM}.png"
PLANT_DUP = f"/source/{PLANT_DIR}/dupes/Qorvex-Dup-Copy.png"


def h(n: int) -> str:
    """A distinct synthetic source hash: the short hashes must differ too."""
    return hashlib.sha256(f"qorvex-{n}".encode()).hexdigest()


def row(n: int, **over):
    base = dict(
        source_hash=h(n),
        short_hash=h(n)[:8],
        status="classified",
        branch="safe",
        needs_review=False,
        format="qorvex-format",
        topic="zhyndel-topic",
        source_path=f"/source/synthetic/qorvex-{n:04d}.png",
        duplicate_paths=(),
        original_sanitized=f"qorvex-{n:04d}",
    )
    base.update(over)
    return gate_4.LedgerRow(**base)


LEDGER = [
    row(1),
    row(2, status="error", format=None, topic=None),
    row(3, needs_review=True),
    row(4, format="unsorted", topic=None),
]


def status_of(ledger):
    by_status: dict[str, int] = {}
    grid: dict[tuple, int] = {}
    for r in ledger:
        by_status[r.status] = by_status.get(r.status, 0) + 1
        key = (r.topic, r.format, r.branch)
        grid[key] = grid.get(key, 0) + 1
    return {
        "counts_by_status": by_status,
        "grid": [
            {"topic": t, "format": f, "branch": b, "adult": is_adult(b), "count": n}
            for (t, f, b), n in grid.items()
        ],
    }


def detail_text(findings) -> str:
    verdict = gate_4.judge(findings, detail=True)
    return "\n".join((*verdict.lines, *verdict.detail))


# --- the verdict ----------------------------------------------------------------------------


def all_ok():
    return [gate_4.Finding(n, True) for n in gate_4.CRITERIA]


def test_all_ok_passes_with_one_line_per_criterion_and_no_figures() -> None:
    verdict = gate_4.judge(all_ok())
    assert verdict.passed
    assert len(verdict.lines) == len(gate_4.CRITERIA) + 1
    assert verdict.lines[-1] == "gate 4 PASS"
    # Exactly the fixed text: no count, no percent (TST-015.D1).
    assert verdict.lines[:-1] == tuple(
        f"gate 4 criterion {n} ({name}): ok" for n, name in gate_4.CRITERIA.items()
    )


def test_a_missing_criterion_fails() -> None:
    findings = [f for f in all_ok() if f.criterion != 5]
    verdict = gate_4.judge(findings, detail=True)
    assert not verdict.passed
    assert verdict.lines[-1] == "gate 4 FAIL"
    assert "gate 4 criterion 5 (adult thumbnails blurred by default): FAIL" in verdict.lines
    assert verdict.detail == ("  5 - NOT_AVAILABLE",)


def test_detail_is_only_added_when_asked_and_only_for_failures() -> None:
    findings = all_ok()
    findings[0] = gate_4.check_reachable(LEDGER, [r.source_hash for r in LEDGER[1:]])
    assert gate_4.judge(findings).detail == ()
    assert gate_4.judge(findings, detail=True).detail == (f"  1 {h(1)[:8]} MISSING",)


def test_detail_never_prints_anything_but_a_short_hash() -> None:
    bad = gate_4.Finding(1, False, ((PLANT_PATH, Code.MISSING),))
    assert (PLANT_PATH, Code.MISSING) in bad.issues  # the plant is held before absence
    text = detail_text([bad])
    assert PLANT_DIR not in text and PLANT_STEM not in text
    assert "  1 ???????? MISSING" in text


# --- 1. reachable ---------------------------------------------------------------------------


def test_reachable_passes_on_the_whole_ledger() -> None:
    assert gate_4.check_reachable(LEDGER, [r.source_hash for r in reversed(LEDGER)]).passed


def test_reachable_flags_missing_extra_and_duplicate() -> None:
    served = [h(1), h(1), h(2), h(3), h(99)]
    finding = gate_4.check_reachable(LEDGER, served)
    assert not finding.passed
    assert set(finding.issues) == {
        (h(4)[:8], Code.MISSING),
        (h(99)[:8], Code.EXTRA),
        (h(1)[:8], Code.DUPLICATE),
    }


def test_reachable_without_the_route_is_not_available() -> None:
    finding = gate_4.check_reachable(LEDGER, None)
    assert finding.issues == (("-", Code.NOT_AVAILABLE),)


# --- 2. counts ------------------------------------------------------------------------------


def test_counts_pass_when_status_matches_the_ledger() -> None:
    status = status_of(LEDGER)
    status["counts_by_status"]["queued"] = 0  # zero entries are ignored
    assert gate_4.check_counts(LEDGER, status).passed


def test_counts_flag_a_status_mismatch() -> None:
    status = status_of(LEDGER)
    status["counts_by_status"]["classified"] += 1
    finding = gate_4.check_counts(LEDGER, status)
    assert finding.issues == (("-", Code.STATUS_MISMATCH),)


def test_counts_flag_a_grid_mismatch_without_the_cell() -> None:
    status = status_of(LEDGER)
    status["grid"][0]["count"] += 1
    assert status["grid"][0]["format"] == "qorvex-format"  # the coinage is in the input
    finding = gate_4.check_counts(LEDGER, status)
    assert finding.issues == (("-", Code.GRID_MISMATCH),)
    assert "qorvex-format" not in detail_text([finding])


def test_counts_on_a_malformed_status_are_unreadable_and_unchained() -> None:
    finding = gate_4.check_counts(LEDGER, {"grid": []})
    assert finding.issues == (("-", Code.UNREADABLE),)
    assert gate_4.check_counts(LEDGER, None).issues == (("-", Code.NOT_AVAILABLE),)


@pytest.mark.parametrize("bad", ["1", 1.0, True, -1, None])
def test_counts_require_plain_ints(bad) -> None:
    status = status_of(LEDGER)
    status["counts_by_status"]["classified"] = bad
    assert gate_4.check_counts(LEDGER, status).issues == (("-", Code.UNREADABLE),)
    status = status_of(LEDGER)
    status["grid"][0]["count"] = bad
    assert gate_4.check_counts(LEDGER, status).issues == (("-", Code.UNREADABLE),)


def test_an_empty_ledger_fails_criteria_1_3_and_4() -> None:
    unavailable = (("-", Code.NOT_AVAILABLE),)
    assert gate_4.check_reachable([], []).issues == unavailable
    assert gate_4.check_review_queue([], []).issues == unavailable
    assert gate_4.check_no_leak([], {"files": "[]"}).issues == unavailable


# --- 3. review queue ------------------------------------------------------------------------


def review_page(*rows) -> str:
    trs = "".join(
        f'<tr data-hash="{r.short_hash}" data-source-hash="{r.source_hash}"><td>x</td></tr>'
        for r in rows
    )
    return f"<table><thead><tr><th>h</th></tr></thead><tbody>{trs}</tbody></table>"


def test_queued_is_needs_review_or_the_unsorted_fallback() -> None:
    assert [gate_4.queued(r) for r in LEDGER] == [False, False, True, True]


def test_queue_entries_read_every_data_hash_row_and_skip_the_header() -> None:
    pages = [review_page(LEDGER[2]), review_page(LEDGER[3]), review_page()]
    assert gate_4.queue_entries(pages) == [h(3), h(4)]


def test_review_queue_passes_when_complete() -> None:
    queue = gate_4.queue_entries([review_page(LEDGER[3], LEDGER[2])])
    assert gate_4.check_review_queue(LEDGER, queue).passed


def test_review_queue_flags_a_missing_and_an_extra_row() -> None:
    queue = gate_4.queue_entries([review_page(LEDGER[2], LEDGER[0])])
    finding = gate_4.check_review_queue(LEDGER, queue)
    assert set(finding.issues) == {(h(4)[:8], Code.NOT_IN_QUEUE), (h(1)[:8], Code.EXTRA)}


def test_review_queue_without_the_route_is_not_available() -> None:
    assert gate_4.check_review_queue(LEDGER, None).issues == (("-", Code.NOT_AVAILABLE),)


# --- 4. no leak -----------------------------------------------------------------------------


def served_bodies(ledger) -> dict[str, str]:
    files = ",".join(f'{{"short_hash":"{r.short_hash}"}}' for r in ledger)
    return {"status": '{"counts_by_status":{}}', "files": f"[{files}]"}


def test_no_leak_passes_when_every_row_is_served_without_a_path() -> None:
    assert gate_4.check_no_leak(LEDGER, served_bodies(LEDGER)).passed


def test_no_leak_fails_when_a_row_is_never_served() -> None:
    finding = gate_4.check_no_leak(LEDGER, served_bodies(LEDGER[:3]))
    assert finding.issues == ((h(4)[:8], Code.NOT_SERVED),)


def test_no_leak_fails_with_nothing_scanned_or_a_missing_source() -> None:
    assert (("-", Code.NOT_AVAILABLE)) in gate_4.check_no_leak(LEDGER, {}).issues
    bodies = {**served_bodies(LEDGER), "events": None}
    assert gate_4.check_no_leak(LEDGER, bodies).issues == (("-", Code.NOT_AVAILABLE),)


PLANTED = row(
    7,
    source_path=PLANT_PATH,
    duplicate_paths=(PLANT_DUP,),
    original_sanitized="qorvex-clean",
)


@pytest.mark.parametrize(
    ("served", "code"),
    [
        (PLANT_PATH, Code.LEAK_PATH),
        (PLANT_PATH.replace("/", "\\/"), Code.LEAK_NAME),  # an escaped "/" still shows the stem
        (PLANT_DUP, Code.LEAK_DUP),
        (PLANT_STEM, Code.LEAK_NAME),
        (PLANT_STEM.upper(), Code.LEAK_NAME),
    ],
)
def test_no_leak_finds_each_planted_secret(served: str, code) -> None:
    bodies = {"files": f'[{{"short_hash":"{PLANTED.short_hash}","x":"{served}"}}]'}
    finding = gate_4.check_no_leak([PLANTED], bodies)
    assert (PLANTED.short_hash, code) in finding.issues


def test_no_leak_finds_escaped_forms() -> None:
    tricky = row(8, source_path='/source/Qorvex & <Zhyndel>/Vruthmar "q".png')
    for body in (
        "/source/Qorvex &amp; &lt;Zhyndel&gt;/Vruthmar &quot;q&quot;.png",
        "%2Fsource%2FQorvex%20%26%20%3CZhyndel%3E%2FVruthmar%20%22q%22.png",
        '/source/Qorvex & <Zhyndel>/Vruthmar \\"q\\".png',
    ):
        finding = gate_4.check_no_leak([tricky], {"ui": f"{tricky.short_hash} {body}"})
        assert (tricky.short_hash, Code.LEAK_PATH) in finding.issues, body


def test_no_leak_handles_a_lone_surrogate_without_raising() -> None:
    odd = row(9, source_path="/source/Qorvex\udcff.png")
    assert odd.source_path.endswith("\udcff.png")  # the plant is held
    leaked = gate_4.check_no_leak([odd], {"ui": f"{odd.short_hash} {odd.source_path}"})
    assert (odd.short_hash, Code.LEAK_PATH) in leaked.issues  # served, it is found
    assert gate_4.check_no_leak([odd], {"ui": odd.short_hash}).passed


def test_raw_name_skips_follow_tst_015_d4() -> None:
    same = row(10, source_path="/source/a/Qorvex-Kept.png", original_sanitized="qorvex-kept")
    short = row(11, source_path="/source/a/Qzx.png", original_sanitized="clean")
    changed = row(12, source_path="/source/a/Zhyndel-Raw.png", original_sanitized="clean")
    with_ext = row(14, source_path="/source/a/Qorvex-Ext.png", original_sanitized="QORVEX-EXT.PNG")
    assert gate_4.raw_stems(same) == []
    assert gate_4.raw_stems(short) == []
    assert gate_4.raw_stems(with_ext) == []  # the stem plus its extension is skipped too
    assert gate_4.raw_stems(changed) == ["Zhyndel-Raw"]
    # The path checks have no skip: a served path still fails even when the stem is skipped.
    finding = gate_4.check_no_leak([same], {"ui": f"{same.short_hash} {same.source_path}"})
    assert finding.issues == ((same.short_hash, Code.LEAK_PATH),)


def test_detail_leaves_out_the_planted_path_and_name_of_a_failing_row() -> None:
    body = f"{PLANTED.short_hash} {PLANT_PATH} {PLANT_DUP} {PLANT_STEM}"
    finding = gate_4.check_no_leak([PLANTED], {"ui": body})
    # The plants were held: the check fires on each before absence is asserted.
    assert set(finding.issues) == {
        (PLANTED.short_hash, Code.LEAK_PATH),
        (PLANTED.short_hash, Code.LEAK_DUP),
        (PLANTED.short_hash, Code.LEAK_NAME),
    }
    text = detail_text([finding])
    assert f"  4 {PLANTED.short_hash} LEAK_PATH" in text
    for secret in (PLANT_DIR, PLANT_STEM, "Qorvex-Dup-Copy", "qorvex-clean", "/source"):
        assert secret.casefold() not in text.casefold()
    assert PLANT_DIR not in repr(finding) and PLANT_DIR not in repr(gate_4.judge([finding], True))


def test_ledger_row_repr_hides_paths_and_names() -> None:
    planted = row(
        13,
        format="Qorvex-Format-Plant",
        topic="Zhyndel-Topic-Plant",
        source_path=PLANT_PATH,
        duplicate_paths=(PLANT_DUP,),
        original_sanitized="Vruthmar-Sanitized-Plant",
    )
    # Each plant is on the instance before its absence from the repr is asserted.
    assert planted.format == "Qorvex-Format-Plant"
    assert planted.topic == "Zhyndel-Topic-Plant"
    assert planted.source_path == PLANT_PATH
    assert planted.duplicate_paths == (PLANT_DUP,)
    assert planted.original_sanitized == "Vruthmar-Sanitized-Plant"
    for text in (repr(planted), str(planted)):
        for secret in (
            "Qorvex-Format-Plant",
            "Zhyndel-Topic-Plant",
            PLANT_DIR,
            "Vruthmar-Sanitized-Plant",
        ):
            assert secret not in text
        assert planted.short_hash in text
    hidden = {f.name for f in dataclasses.fields(planted) if not f.repr}
    assert hidden == {"format", "topic", "source_path", "duplicate_paths", "original_sanitized"}


# --- 6. report ------------------------------------------------------------------------------

CLEAN_REPORT = (
    "<!doctype html><html><head><meta charset='utf-8'><style>td{color:#123}</style></head>"
    "<body><a href='#errors'>errors</a><table><tr data-hash='0000000a'><td>x</td></tr></table>"
    "</body></html>"
)


def test_a_self_contained_report_passes() -> None:
    assert gate_4.check_report(CLEAN_REPORT).passed


@pytest.mark.parametrize(
    ("snippet", "code"),
    [
        ("<script src='/static/app.js'></script>", Code.EXTERNAL_REF),
        ("<link rel='stylesheet' href='//cdn.example/x.css'>", Code.EXTERNAL_REF),
        ("<a href='https://example.invalid/'>x</a>", Code.EXTERNAL_REF),
        ("<p>see http://example.invalid</p>", Code.EXTERNAL_REF),
        ("<style>@import 'x.css';</style>", Code.EXTERNAL_REF),
        ("<style>body{background:url(x.png)}</style>", Code.EXTERNAL_REF),
        ("<form action='/api/files'></form>", Code.EXTERNAL_REF),
        ("<meta http-equiv='refresh' content='5'>", Code.EXTERNAL_REF),
        ("<meta http-equiv=' Refresh ' content='0;url=#top'>", Code.EXTERNAL_REF),
        ("<img alt='' src='#'>", Code.THUMB_IN_REPORT),
        ("<p>/thumbs/" + h(1) + "</p>", Code.THUMB_IN_REPORT),
        ("<object data='data:image/png;base64,AAAA'></object>", Code.THUMB_IN_REPORT),
    ],
)
def test_report_flags_each_external_reference_or_thumbnail(snippet: str, code) -> None:
    report = CLEAN_REPORT.replace("</body>", snippet + "</body>")
    finding = gate_4.check_report(report)
    assert not finding.passed
    assert (("-", code)) in finding.issues


def test_report_missing_is_not_available() -> None:
    assert gate_4.check_report(None).issues == (("-", Code.NOT_AVAILABLE),)


# --- main -----------------------------------------------------------------------------------


def test_main_without_the_app_dsn_fails_with_fixed_text(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_DB_DSN", raising=False)
    assert gate_4.main([]) == 1
    out = capsys.readouterr()
    assert out.err == f"gate 4 FAIL: {gate_4.NO_APP_DSN}\n" and out.out == ""


def test_main_hides_a_failure_message(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(dsn: str, engine=None):
        raise RuntimeError(PLANT_PATH)

    monkeypatch.setenv("APP_DB_DSN", "postgresql://qorvex:Zhyndel-Pass@db:5432/x")
    monkeypatch.setattr(gate_4, "run", boom)
    with pytest.raises(RuntimeError, match=PLANT_DIR):  # the plant is held by the failure
        boom("x")
    assert gate_4.main([]) == 1
    err = capsys.readouterr().err
    assert err == "gate 4 FAIL: run errored (RuntimeError)\n"
    assert PLANT_DIR not in err and "Zhyndel-Pass" not in err


def test_main_prints_the_verdict_only(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("APP_DB_DSN", "postgresql://qorvex@db/x")
    monkeypatch.setattr(gate_4, "run", lambda dsn, engine=None: all_ok())
    assert gate_4.main([]) == 0
    assert capsys.readouterr().out.splitlines() == list(gate_4.judge(all_ok()).lines)


def test_the_gate_probe_makes_no_model_call() -> None:
    assert gate_4.NoModels().loaded_models() is None


def test_the_gate_names_every_scanned_source() -> None:
    assert gate_4.SOURCES == ("status", "files", "review", "ui", "events", "report")


# --- 5. blur --------------------------------------------------------------------------------

ADULT = row(20, branch=ADULT_BRANCH)
SAFE = row(21, branch="safe")
UNBRANCHED = row(22, branch=None)


def thumb(r, blur: str | None) -> str:
    flag = "" if blur is None else f' data-blur="{blur}"'
    src = f"/thumbs/{r.source_hash}"
    return f'<img class="thumb" src="{src}" data-hash="{r.short_hash}"{flag} alt="">'


def test_the_adult_rows_are_the_is_adult_ones() -> None:
    assert [is_adult(r.branch) for r in (ADULT, SAFE, UNBRANCHED)] == [True, False, False]


def test_blur_passes_when_every_adult_thumbnail_is_blurred() -> None:
    page = thumb(ADULT, "1") + thumb(SAFE, "0") + thumb(UNBRANCHED, "0")
    assert gate_4.check_blur([ADULT, SAFE, UNBRANCHED], [page, thumb(ADULT, "1")]).passed


@pytest.mark.parametrize("blur", ["0", None, "true", ""])
def test_blur_flags_an_adult_thumbnail_not_blurred_by_default(blur) -> None:
    pages = [thumb(ADULT, "1"), thumb(ADULT, blur)]
    finding = gate_4.check_blur([ADULT, SAFE], pages)
    assert finding.issues == ((ADULT.short_hash, Code.NOT_BLURRED),)


def test_blur_ignores_a_non_thumb_image_and_safe_rows() -> None:
    other = f'<img class="logo" data-hash="{ADULT.short_hash}">'
    pages = [thumb(ADULT, "1"), other, thumb(SAFE, "0")]
    assert gate_4.check_blur([ADULT, SAFE], pages).passed


def test_blur_needs_at_least_one_adult_thumbnail() -> None:
    finding = gate_4.check_blur([ADULT, SAFE], [thumb(SAFE, "0")])
    assert finding.issues == (("-", Code.NO_ADULT_THUMB),)
    assert gate_4.check_blur([SAFE], [thumb(SAFE, "0")]).passed  # no adult rows, nothing owed


def test_blur_without_html_or_ledger_is_not_available() -> None:
    assert gate_4.check_blur([ADULT], None).issues == (("-", Code.NOT_AVAILABLE),)
    assert gate_4.check_blur([], [thumb(ADULT, "1")]).issues == (("-", Code.NOT_AVAILABLE),)


# --- 2. the grid's safe-vs-adult flag (API-001.D8) ------------------------------------------


def test_counts_pass_with_an_adult_cell() -> None:
    ledger = [*LEDGER, ADULT]
    status = status_of(ledger)
    assert any(cell["adult"] for cell in status["grid"])
    assert gate_4.check_counts(ledger, status).passed


def test_counts_flag_a_wrong_adult_flag() -> None:
    ledger = [*LEDGER, ADULT]
    status = status_of(ledger)
    for cell in status["grid"]:
        if cell["branch"] == ADULT_BRANCH:
            cell["adult"] = False
    assert gate_4.check_counts(ledger, status).issues == (("-", Code.GRID_MISMATCH),)


@pytest.mark.parametrize("bad", [None, 1, "true"])
def test_counts_require_a_bool_adult_flag(bad) -> None:
    status = status_of(LEDGER)
    status["grid"][0]["adult"] = bad
    assert gate_4.check_counts(LEDGER, status).issues == (("-", Code.UNREADABLE),)


# --- 7. compose -----------------------------------------------------------------------------

LOCAL_COMPOSE = """
services:
  qorvex-db:
    image: postgres:16
  qorvex-proxy:
    image: nginx:1-alpine
    ports:
      - "127.0.0.1:8000:8000"
      - target: 9000
        published: 9000
        host_ip: 127.0.0.1
"""


def test_compose_publishing_localhost_only_passes() -> None:
    assert gate_4.check_compose(LOCAL_COMPOSE).passed


def test_the_repo_compose_file_passes() -> None:
    assert gate_4.check_compose(gate_4.read_compose()).passed


@pytest.mark.parametrize(
    "entry",
    [
        '"8000:8000"',
        '"8000"',
        "8000",
        '"0.0.0.0:8000:8000"',
        '"[::1]:8000:8000"',
        '"${QORVEX_HOST}:8000:8000"',
        '"127.0.0.1::8000"',
        "{target: 8000, published: 8000}",
        "{target: 8000, published: 8000, host_ip: 0.0.0.0}",
    ],
)
def test_compose_flags_a_port_beyond_localhost(entry: str) -> None:
    text = LOCAL_COMPOSE + f"  qorvex-app:\n    image: x\n    ports:\n      - {entry}\n"
    finding = gate_4.check_compose(text)
    assert finding.issues == (("-", Code.PORT_NOT_LOCAL),)
    assert "qorvex-app" not in detail_text([finding])


def test_compose_flags_the_host_network() -> None:
    text = LOCAL_COMPOSE + "  qorvex-app:\n    image: x\n    network_mode: host\n"
    assert gate_4.check_compose(text).issues == (("-", Code.HOST_NETWORK),)


@pytest.mark.parametrize("text", ["services: [", "- a list", "services:\n  x: 3\n", ""])
def test_compose_that_cannot_be_read_fails(text: str) -> None:
    finding = gate_4.check_compose(text)
    assert finding.issues == (("-", Code.UNREADABLE),)


def test_compose_missing_is_not_available(tmp_path: Path) -> None:
    assert gate_4.read_compose(tmp_path / "missing.yml") is None
    assert gate_4.check_compose(None).issues == (("-", Code.NOT_AVAILABLE),)


# --- 5. the served `blurred` flag (API-001.3) -----------------------------------------------


def test_blur_flags_pass_when_each_equals_is_adult() -> None:
    flags = {ADULT.source_hash: True, SAFE.source_hash: False, UNBRANCHED.source_hash: False}
    finding = gate_4.check_blur([ADULT, SAFE, UNBRANCHED], [thumb(ADULT, "1")], flags)
    assert finding.passed


@pytest.mark.parametrize(
    ("which", "value"),
    [("adult", False), ("safe", True), ("adult", None), ("adult", 1), ("adult", "true")],
)
def test_blur_flags_flag_a_wrong_or_missing_flag(which: str, value) -> None:
    flags = {ADULT.source_hash: True, SAFE.source_hash: False}
    target = ADULT if which == "adult" else SAFE
    flags[target.source_hash] = value
    finding = gate_4.check_blur([ADULT, SAFE], [thumb(ADULT, "1")], flags)
    assert finding.issues == ((target.short_hash, Code.BLUR_FLAG),)


def test_blur_flags_run_while_the_html_is_not_available() -> None:
    finding = gate_4.check_blur([ADULT, SAFE], None, {ADULT.source_hash: False})
    assert set(finding.issues) == {
        (ADULT.short_hash, Code.BLUR_FLAG),
        (SAFE.short_hash, Code.BLUR_FLAG),  # never served a flag
        ("-", Code.NOT_AVAILABLE),
    }


# --- the runner's pieces --------------------------------------------------------------------


class FakeResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = {"content-type": "text/event-stream"}


class FakeClient:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.paths: list[str] = []

    def get(self, path: str, params=None) -> FakeResponse:
        self.paths.append(path)
        return self.response


def test_events_keeps_a_stream_with_a_status_frame() -> None:
    frame = 'event: status\ndata: {"counts_by_status":{}}\n\n'
    client = FakeClient(FakeResponse(200, frame))
    text = gate_4._events(client)
    assert client.paths == ["/api/events"]
    assert text is not None and frame in text and "content-type: text/event-stream" in text


@pytest.mark.parametrize(
    "response",
    [
        FakeResponse(404, '{"detail":"Not Found"}'),
        FakeResponse(200, ": keep-alive\n\n"),
        FakeResponse(200, 'event: unavailable\ndata: {"detail":"database unavailable"}\n\n'),
    ],
)
def test_events_without_a_status_frame_is_not_available(response) -> None:
    assert gate_4._events(FakeClient(response)) is None


def test_served_repr_hides_every_content_field() -> None:
    plant = "Qorvex-Served-Plant"
    served = gate_4.Served(
        files=[plant],
        status={"grid": [{"topic": plant}]},
        queue=[plant],
        html=[plant],
        report=plant,
        bodies={"ui": plant},
    )
    # Each plant is held before its absence from the repr is asserted.
    assert served.files == [plant] and served.queue == [plant] and served.html == [plant]
    assert served.report == plant and plant in str(served.status) and served.bodies["ui"] == plant
    assert plant not in repr(served) and plant not in str(served)
    assert all(not f.repr for f in dataclasses.fields(served))
