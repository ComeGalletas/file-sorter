"""API-001.5: `render_report` on hand-built views (no database)."""

from collections.abc import Iterator
from datetime import UTC, datetime

from classifier.api.report import NOT_CLASSIFIED, branch_label, render_report
from classifier.api.views import (
    ADULT_BRANCH,
    NOT_AVAILABLE,
    FileRow,
    GridCell,
    LastError,
    ModelView,
    RunView,
    StatusView,
    is_adult,
)
from classifier.ui.html import DASH

T = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
HASH = "ab" * 32


def _status(**kw: object) -> StatusView:
    base: dict[str, object] = {
        "run": None,
        "imgs_per_min": None,
        "counts_by_status": {"queued": 0, "classified": 1},
        "grid": [],
        "loaded_models": NOT_AVAILABLE,
        "last_error": None,
    }
    base.update(kw)
    return StatusView(**base)  # type: ignore[arg-type]


def _row(**kw: object) -> FileRow:
    base: dict[str, object] = {
        "source_hash": HASH,
        "short_hash": HASH[:8],
        "sanitized_name": "qorvex.png",
        "ext": "png",
        "status": "classified",
        "branch": "safe",
        "format": "Zhyndelform",
        "topic": None,
        "nsfw_level": None,
        "nsfw_traces": None,
        "cross_check_disagrees": False,
        "needs_review": False,
        "review_reason": None,
        "error": None,
        "updated_at": T,
    }
    base.update(kw)
    return FileRow(**base)  # type: ignore[arg-type]


def test_empty_ledger_and_no_run() -> None:
    html = render_report(_status(), [])
    assert html.startswith("<!doctype html>")
    assert "<p>no run</p>" in html
    assert f"<p>{NOT_AVAILABLE}</p>" in html
    assert "<tr data-hash=" not in html


def test_run_models_and_last_error_render() -> None:
    run = RunView(
        id=1,
        kind="dry_run",
        state="finished",
        started_at=T,
        finished_at=T,
        counts={"classify": {"classified": 4}},
        error=None,
    )
    status = _status(
        run=run,
        imgs_per_min=2.25,
        loaded_models=[ModelView(name="qorvex:1b", size_vram=10)],
        last_error=LastError(short_hash="deadbeef", status="failed", error="E_X", updated_at=T),
    )
    html = render_report(status, [])
    assert "<td>dry_run</td>" in html and "<td>2.2</td>" in html
    assert "<td>classify</td><td>classified</td><td class=n>4</td>" in html
    assert "qorvex:1b" in html and "deadbeef" in html and "E_X" in html


def test_files_are_consumed_once_in_order() -> None:
    hashes = [f"{i:02d}" * 32 for i in range(3)]

    def rows() -> Iterator[FileRow]:
        for h in hashes:
            yield _row(source_hash=h, short_hash=h[:8])

    html = render_report(_status(), rows())
    positions = [html.index(f'data-hash="{h[:8]}"') for h in hashes]
    assert positions == sorted(positions)


def test_unsanitized_row_shows_a_dash_not_a_name() -> None:
    html = render_report(_status(), [_row(sanitized_name=None, status="queued", branch=None)])
    row = html[html.index("<tr data-hash=") :]
    assert f"<td>{HASH[:8]}</td><td>{DASH}</td><td>queued</td>" in row


def test_branch_label_follows_is_adult() -> None:
    assert is_adult(ADULT_BRANCH) and branch_label(ADULT_BRANCH) == "adult"
    assert branch_label("safe") == "safe"
    assert branch_label(None) == NOT_CLASSIFIED


def test_grid_three_way_split() -> None:
    grid = [
        GridCell(topic="QorA", format="F", branch=ADULT_BRANCH, adult=True, count=2),
        GridCell(topic="QorS", format="F", branch="safe", adult=False, count=3),
        GridCell(topic="QorN", format=None, branch=None, adult=False, count=1),
    ]
    html = render_report(_status(grid=grid), [])
    for title, topic in (("safe", "QorS"), ("adult", "QorA"), (NOT_CLASSIFIED, "QorN")):
        start = html.index(f"<h2>Topic × format: {title}</h2>")
        section = html[start : html.find("<h2>", start + 1)]
        assert f"<th>{topic}</th>" in section
        for other in {"QorS", "QorA", "QorN"} - {topic}:
            assert other not in section


def test_no_script_img_or_url() -> None:
    html = render_report(_status(), [_row(sanitized_name='"><script>x</script>')])
    # Proved served first: the planted row is rendered, its name escaped.
    assert f'data-hash="{HASH[:8]}"' in html
    assert "&quot;&gt;&lt;script&gt;x&lt;/script&gt;" in html
    lowered = html.lower()
    for bad in ("<script", "<img", "<link", "src=", "href="):
        assert bad not in lowered
    assert "http:" not in lowered and "https:" not in lowered and "//" not in lowered
