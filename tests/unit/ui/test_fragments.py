"""API-001.4: the fragment builders on hand-built views (no database)."""

import re
from datetime import UTC, datetime

import pytest

from classifier.api import app as api_app
from classifier.api.views import (
    ADULT_BRANCH,
    NOT_AVAILABLE,
    PER_PAGE,
    FileRow,
    StatusView,
    is_adult,
)
from classifier.ui import fragments, routes

T = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
WRITE_MARKERS = ("<form", "<button", "hx-post", "hx-put", "hx-patch", "hx-delete", "method=")
THUMB = re.compile(
    r'<img class="thumb" src="/thumbs/([0-9a-f]{64})" data-hash="([0-9a-f]{8})" '
    r'data-blur="([01])" alt="">'
)


def _row(n: int = 0, **kw: object) -> FileRow:
    h = f"{n:064x}"
    base: dict[str, object] = {
        "source_hash": h,
        "short_hash": h[:8],
        "sanitized_name": "qorvex.png",
        "ext": "png",
        "status": "classified",
        "branch": "safe",
        "format": "Zhyndelform",
        "topic": None,
        "nsfw_level": None,
        "nsfw_traces": None,
        "cross_check_disagrees": False,
        "needs_review": True,
        "review_reason": "unsorted",
        "error": None,
        "updated_at": T,
    }
    base.update(kw)
    base["blurred"] = is_adult(base["branch"])  # type: ignore[arg-type]
    return FileRow(**base)  # type: ignore[arg-type]


def _status() -> StatusView:
    return StatusView(
        run=None,
        imgs_per_min=None,
        counts_by_status={"classified": 1},
        grid=[],
        loaded_models=NOT_AVAILABLE,
        last_error=None,
    )


@pytest.mark.parametrize(("branch", "blur"), [(ADULT_BRANCH, "1"), ("safe", "0"), (None, "0")])
def test_thumb_markup_is_d8_exactly(branch: str | None, blur: str) -> None:
    r = _row(7, branch=branch)
    match = THUMB.fullmatch(fragments.thumb(r))
    assert match is not None
    assert match.groups() == (r.source_hash, r.short_hash, blur)


def test_thumb_has_no_title_and_an_empty_alt() -> None:
    out = fragments.thumb(_row(sanitized_name="qorvex-name.png"))
    assert "title" not in out and 'alt=""' in out and "qorvex-name" not in out


def test_review_row_attributes_and_cells() -> None:
    r = _row(3, nsfw_level="suggestive", nsfw_traces=True, cross_check_disagrees=True)
    out = fragments.review([r], 1)
    assert f'<tr data-hash="{r.short_hash}" data-source-hash="{r.source_hash}">' in out
    assert "<td>suggestive</td><td>yes</td><td>yes</td><td>unsorted</td>" in out
    assert 'class="more"' not in out  # a short page is the last one


def test_full_page_ends_with_a_loader_for_the_next() -> None:
    rows = [_row(i) for i in range(PER_PAGE)]
    out = fragments.review(rows, 4)
    assert out.count("<tr data-hash=") == PER_PAGE
    assert 'hx-get="/ui/review?page=5" hx-trigger="revealed"' in out
    assert 'hx-get="/ui/errors?page=2"' in fragments.errors(rows, 1)


def test_empty_page_is_empty() -> None:
    assert fragments.review([], 9) == ""
    assert fragments.errors([], 9) == ""


def test_every_value_is_escaped() -> None:
    r = _row(
        sanitized_name='"><script>alert(1)</script>',
        format='Zhyndel" onmouseover="x',
        topic="<b>Qorvex</b>",
        error="<i>E</i>",
    )
    for out in (fragments.review([r], 1), fragments.latest([r]), fragments.errors([r], 1)):
        assert f'data-hash="{r.short_hash}"' in out  # served
        lowered = out.lower()
        for bad in ("<script", 'onmouseover="', "<b>", "<i>"):
            assert bad not in lowered
    assert "&lt;script&gt;" in fragments.review([r], 1)
    assert "&lt;i&gt;E&lt;/i&gt;" in fragments.errors([r], 1)


def test_errors_show_hash_status_code_and_no_retry() -> None:
    r = _row(5, status="error", error="E_DECODE")
    out = fragments.errors([r], 1)
    assert f"<td>{r.short_hash}</td><td>error</td><td>E_DECODE</td>" in out
    assert "retry" not in out.lower()


def test_latest_labels_branches_and_carries_thumbs() -> None:
    rows = [_row(1, branch=ADULT_BRANCH), _row(2, branch="safe"), _row(3, branch=None)]
    out = fragments.latest(rows)
    assert [m[2] for m in THUMB.findall(out)] == ["1", "0", "0"]
    assert "<td>adult</td>" in out and "<td>safe</td>" in out and "<td>not classified</td>" in out


def test_no_write_markers_anywhere() -> None:
    rows = [_row(i) for i in range(PER_PAGE)]
    outs = [
        fragments.banner(_status()),
        fragments.grid(_status()),
        fragments.latest(rows[:20]),
        fragments.errors(rows, 1),
        fragments.review(rows, 1),
        routes.INDEX.read_text(encoding="utf-8"),
    ]
    for out in outs:
        lowered = out.lower()
        for marker in WRITE_MARKERS:
            assert marker not in lowered, marker


def test_page_bound_matches_the_api() -> None:
    assert routes.MAX_PAGE == api_app.MAX_PAGE


def test_csp_forbids_inline_script_and_other_origins() -> None:
    assert "script-src 'self'" in routes.CSP and "unsafe-inline" not in routes.CSP.split(";")[1]
    assert "default-src 'none'" in routes.CSP and "form-action 'none'" in routes.CSP
