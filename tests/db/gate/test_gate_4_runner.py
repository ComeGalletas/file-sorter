"""TST-015.1.3, .1.10: gate 4's runner over a migrated test schema, through `create_app` in-process.

Rows are synthetic and committed through their own connection (the app reads on its own
read-only engine), then deleted by hash. Plants are proved held (read into the ledger) and
served (no `NOT_SERVED`) before their absence is asserted.

The UI scenarios are built explicitly, so these tests hold whether or not the real UI
(API-001.4) is on `main` (TST-015.1.10). The `ui` fixture wraps `create_app` and first strips
every UI route (`/` and `/ui/*`), then either serves nothing there (the UI absent: criteria 3,
4 and 5 must be `NOT_AVAILABLE`, never pass) or mounts `StandIn`, a minimal synthetic router
that serves the API-001.D8/D9 markup from the ledger's own views. Tests without the fixture
run against API-001.4's real routes on `main` (TST-015.1.4).
"""

import hashlib
import importlib.util
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import select

import classifier.api.app as app_module
from classifier.api.app import read_only_engine
from classifier.api.views import ADULT_BRANCH, PER_PAGE, FileFilters, FileRow, file_row, rows_query
from classifier.db.models import File
from classifier.ui.html import esc

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_4.py"
_spec = importlib.util.spec_from_file_location("gate_4_runner", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_4)

Code = gate_4.Code
BASE = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
PLANT_DIR = "Qorvex-Runner-Plant"
PLANT_STEM = "Zhyndel-Raw-Runner"
PLANT_DUP_STEM = "Vruthmar-Dup-Runner"
NOT_AVAILABLE = (("-", Code.NOT_AVAILABLE),)
STAND_IN_LATEST = 20  # as API-001.D1's dashboard: the newest rows only

Seed = Callable[..., str]


@pytest.fixture
def seed(migrated_db: str) -> Iterator[Seed]:
    hashes: list[str] = []
    conn = psycopg.connect(migrated_db, autocommit=True)

    def add(**cols: Any) -> str:
        source_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        row: dict[str, Any] = {
            "source_hash": source_hash,
            "short_hash": source_hash[:8],
            # Not derived from the hash, which is served on purpose: the stem would match it.
            "source_path": f"/source/qorvex/raw-{uuid.uuid4().hex[:12]}.png",
            "source_mtime": BASE,
            "ext": "png",
            "status": "classified",
            "branch": "safe",
            "format": "qorvex-format",
            "topic": "zhyndel-topic",
            "original_sanitized": f"clean-{source_hash[:6]}",
            "updated_at": BASE,
        }
        row.update(cols)
        names = ", ".join(row)
        marks = ", ".join(f"%({k})s" for k in row)
        hashes.append(source_hash)
        conn.execute(f"insert into files ({names}) values ({marks})", row)
        return source_hash

    try:
        yield add
    finally:
        try:
            if hashes:
                conn.execute("delete from files where source_hash = any(%s)", [hashes])
        finally:
            conn.close()


# --- the UI scenarios (TST-015.1.10) ----------------------------------------------------------


def _is_ui(route: Any) -> bool:
    path = getattr(route, "path", "")
    return path == "/" or path.startswith("/ui/")


@dataclass(frozen=True)
class StandIn:
    """A synthetic stand-in for API-001.4's routes, serving the D8/D9 markup only.

    `adult_blur` overrides `data-blur` on adult thumbnails (a negative case); `missing` is a
    route it doesn't serve; `leak_on` is a route that also prints every row's `source_path`."""

    adult_blur: str | None = None
    missing: str | None = None
    leak_on: str | None = None

    def thumb(self, r: FileRow) -> str:
        blur = "1" if r.blurred else "0"  # FileRow.blurred is is_adult(branch)
        if r.blurred and self.adult_blur is not None:
            blur = self.adult_blur
        return (
            f'<img class="thumb" src="/thumbs/{esc(r.source_hash)}" '
            f'data-hash="{esc(r.short_hash)}" data-blur="{blur}" alt="">'
        )

    def router(self) -> APIRouter:
        router = APIRouter()

        def rows(request: Request) -> list[FileRow]:
            with request.app.state.engine.connect() as conn:  # the gate's read-only engine
                return [file_row(m) for m in conn.execute(rows_query(FileFilters())).mappings()]

        def leaked(request: Request, route: str) -> str:
            if route != self.leak_on:
                return ""
            with request.app.state.engine.connect() as conn:
                paths = conn.execute(select(File.source_path)).scalars()
                return "".join(f"<p>{path}</p>" for path in paths)

        def page_of(items: list[FileRow], page: int) -> list[FileRow]:
            return items[(page - 1) * PER_PAGE : page * PER_PAGE]

        def serve(route: str, build: Callable[[Request, int], str]) -> None:
            if route == self.missing:
                return

            @router.get(route)
            def handler(request: Request, page: int = 1) -> Response:
                body = build(request, page) + leaked(request, route)
                return HTMLResponse(body)

        def tr(r: FileRow, queued: bool = False) -> str:
            source = f' data-source-hash="{esc(r.source_hash)}"' if queued else ""
            cells = f"<td>{self.thumb(r)}</td><td>{esc(r.sanitized_name)}</td>"
            return f'<tr data-hash="{esc(r.short_hash)}"{source}>{cells}</tr>'

        serve("/", lambda req, page: '<section data-fragment="/ui/latest"></section>')
        serve("/ui/app.js", lambda req, page: "// stand-in")
        serve("/ui/banner", lambda req, page: "<p>banner</p>")
        serve("/ui/grid", lambda req, page: "<table></table>")
        serve(
            "/ui/latest",
            lambda req, page: "".join(tr(r) for r in rows(req)[:STAND_IN_LATEST]),
        )
        serve(
            "/ui/errors",
            lambda req, page: "".join(
                tr(r) for r in page_of([r for r in rows(req) if r.error], page)
            ),
        )
        serve(
            "/ui/review",
            lambda req, page: "".join(
                tr(r, queued=True)
                for r in page_of(
                    [r for r in rows(req) if r.needs_review or r.format == gate_4.UNSORTED_FORMAT],
                    page,
                )
            ),
        )
        return router


UI = Callable[[StandIn | None], None]


@pytest.fixture
def ui(monkeypatch: pytest.MonkeyPatch) -> UI:
    """`ui(None)`: the UI absent; `ui(StandIn(...))`: the stand-in serves it. Either way the
    app's own UI routes, if any, are taken out first: `create_app` gets an empty router for
    API-001.4's `ui_router` (FastAPI wraps an included router as one entry, so its routes
    can't be filtered by path afterwards), and any plain UI route left is dropped. The
    scenario tests assert the outcome, so a UI mounted another way fails them loudly."""
    real = app_module.create_app
    monkeypatch.setattr(app_module, "ui_router", lambda **_: APIRouter(), raising=False)

    def use(stand_in: StandIn | None) -> None:
        def create(*args: Any, **kwargs: Any) -> Any:
            app = real(*args, **kwargs)
            app.router.routes[:] = [r for r in app.router.routes if not _is_ui(r)]
            if stand_in is not None:
                app.include_router(stand_in.router())
            return app

        monkeypatch.setattr(app_module, "create_app", create)

    return use


def _ledger(migrated_db: str) -> list[Any]:
    engine = read_only_engine(migrated_db)
    try:
        return gate_4.read_ledger(engine)
    finally:
        engine.dispose()


def _seed_folder(seed: Seed) -> tuple[list[str], str]:
    """More than one page of rows, an adult row, a review row, an unsorted row and a plant.

    The adult row is the newest and isn't queued: only the latest fragment shows its
    thumbnail, as on a real dashboard (the NO_ADULT_THUMB miss on #214)."""
    hashes = [seed() for _ in range(PER_PAGE + 3)]
    hashes.append(seed(branch=ADULT_BRANCH, updated_at=BASE + timedelta(hours=1)))
    hashes.append(seed(needs_review=True, review_reason="nsfw_disagreement"))
    hashes.append(seed(format="unsorted", topic=None, status="classified"))
    hashes.append(seed(status="error", error="qorvex_error", format=None, topic=None))
    planted = seed(
        source_path=f"/source/{PLANT_DIR}/{PLANT_STEM}.png",
        duplicate_paths=[f"/source/{PLANT_DIR}/{PLANT_DUP_STEM}.png"],
        original_sanitized="qorvex-clean",
    )
    hashes.append(planted)
    return hashes, planted


def _run(migrated_db: str) -> dict[int, Any]:
    return {f.criterion: f for f in gate_4.run(migrated_db, read_only_engine(migrated_db))}


def test_the_runner_reads_the_whole_ledger_and_holds_the_plants(migrated_db, seed) -> None:
    hashes, planted = _seed_folder(seed)
    ledger = _ledger(migrated_db)
    assert {r.source_hash for r in ledger} == set(hashes)  # this test's rows, and only them
    [row] = [r for r in ledger if r.source_hash == planted]
    assert row.source_path == f"/source/{PLANT_DIR}/{PLANT_STEM}.png"
    assert row.duplicate_paths == (f"/source/{PLANT_DIR}/{PLANT_DUP_STEM}.png",)
    assert gate_4.raw_stems(row) == [PLANT_STEM, PLANT_DUP_STEM]
    assert PLANT_DIR not in repr(row)


def test_without_the_ui_criteria_3_4_and_5_are_not_available(migrated_db, seed, ui) -> None:
    ui(None)
    _seed_folder(seed)
    findings = _run(migrated_db)
    assert findings[1].passed, findings[1].issues  # paged past PER_PAGE to the empty page
    assert findings[2].passed, findings[2].issues  # counts and the grid, adult flag included
    assert findings[6].passed, findings[6].issues  # the real report is self-contained
    assert findings[7].passed, findings[7].issues
    # Every row was served (no NOT_SERVED), the plant included, so the absence of LEAK_* means
    # something; the only issue is the UI bodies that aren't served. Criterion 5's `blurred`
    # flags (API-001.3) are checked and agree: only its HTML is missing.
    for criterion in (3, 4, 5):
        assert findings[criterion].issues == NOT_AVAILABLE, criterion


def test_with_the_ui_every_criterion_passes(migrated_db, seed, ui) -> None:
    ui(StandIn())
    _seed_folder(seed)
    ledger, served = gate_4.serve(migrated_db, read_only_engine(migrated_db))
    adult = [r for r in ledger if r.branch == ADULT_BRANCH]
    assert adult and not any(gate_4.queued(r) for r in adult)  # not queued: latest only
    assert served.html is not None
    assert any(f'data-hash="{adult[0].short_hash}" data-blur="1"' in p for p in served.html)
    assert all(served.bodies[s] is not None for s in gate_4.SOURCES)
    findings = gate_4.evaluate(ledger, served, gate_4.read_compose())
    for finding in findings:
        assert finding.passed, (finding.criterion, finding.issues)


def test_with_the_ui_an_unblurred_adult_thumbnail_fails(migrated_db, seed, ui) -> None:
    ui(StandIn(adult_blur="0"))
    _seed_folder(seed)
    adult = [r.short_hash for r in _ledger(migrated_db) if r.branch == ADULT_BRANCH]
    findings = _run(migrated_db)
    assert findings[5].issues == ((adult[0], Code.NOT_BLURRED),)


@pytest.mark.parametrize("route", ["/ui/latest", "/ui/errors", "/ui/app.js"])
def test_with_the_ui_a_path_on_any_fragment_fails(migrated_db, seed, ui, route: str) -> None:
    ui(StandIn(leak_on=route))
    _, planted = _seed_folder(seed)
    assert any(r.source_hash == planted for r in _ledger(migrated_db))  # the plant is held
    findings = _run(migrated_db)
    issues = set(findings[4].issues)
    assert (planted[:8], Code.LEAK_PATH) in issues and (planted[:8], Code.LEAK_NAME) in issues
    assert not any(code is Code.NOT_SERVED for _, code in issues)


@pytest.mark.parametrize(
    "route",
    ["/", "/ui/app.js", "/ui/banner", "/ui/grid", "/ui/latest", "/ui/errors", "/ui/review"],
)
def test_with_a_ui_route_missing_criterion_4_is_not_available(
    migrated_db, seed, ui, route: str
) -> None:
    ui(StandIn(missing=route))
    _seed_folder(seed)
    findings = _run(migrated_db)
    assert findings[4].issues == NOT_AVAILABLE
    if route in ("/ui/latest", "/ui/errors", "/ui/review"):
        assert findings[5].issues == NOT_AVAILABLE


# --- the real UI (API-001.4 on main; TST-015.1.4) ---------------------------------------------


def test_the_real_ui_passes_every_criterion(migrated_db, seed) -> None:
    """No `ui` fixture: `create_app` serves API-001.4's own routes and markup."""
    _, planted = _seed_folder(seed)
    ledger, served = gate_4.serve(migrated_db, read_only_engine(migrated_db))
    [adult] = [r for r in ledger if r.branch == ADULT_BRANCH]
    assert not gate_4.queued(adult)  # not queued: only the real latest fragment shows it
    assert served.html is not None and all(served.bodies[s] is not None for s in gate_4.SOURCES)
    thumbs = [
        attrs
        for page in served.html
        for tag, attrs in gate_4._tags(page)
        if tag == "img" and attrs.get("data-hash") == adult.short_hash
    ]
    assert thumbs and all(a.get("data-blur") == "1" for a in thumbs)  # D8, by default
    assert any(planted[:8] in (served.bodies[s] or "") for s in ("files", "report"))
    findings = gate_4.evaluate(ledger, served, gate_4.read_compose())
    for finding in findings:
        assert finding.passed, (finding.criterion, finding.issues)


def test_main_detail_with_the_real_ui_passes(
    migrated_db, seed, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_folder(seed)
    code, lines = _main_detail(migrated_db, monkeypatch, capsys)
    assert code == 0, lines
    assert lines[-1] == "gate 4 PASS" and len(lines) == len(gate_4.CRITERIA) + 1  # no detail


def test_the_report_holds_every_row_and_no_plant(migrated_db, seed) -> None:
    _, planted = _seed_folder(seed)
    ledger, served = gate_4.serve(migrated_db, read_only_engine(migrated_db))
    report = served.report
    assert report is not None and served.bodies["report"] == report
    # Every row is in the report (held), the plant included, before its absence is asserted.
    assert all(f'data-hash="{r.short_hash}"' in report for r in ledger)
    assert planted[:8] in report
    for secret in (PLANT_DIR, PLANT_STEM, PLANT_DUP_STEM, "/source/"):
        assert secret not in report
    assert gate_4.check_report(report).passed


def test_the_served_blurred_flags_match_is_adult(migrated_db, seed) -> None:
    _seed_folder(seed)
    ledger, served = gate_4.serve(migrated_db, read_only_engine(migrated_db))
    adult = [r for r in ledger if r.branch == ADULT_BRANCH]
    assert adult and served.blurred is not None  # an adult row is there, and flags were served
    assert all(served.blurred[r.source_hash] is True for r in adult)
    assert gate_4.check_blur(ledger, None, served.blurred).issues == NOT_AVAILABLE


def test_the_runner_fails_on_an_empty_ledger(migrated_db) -> None:
    assert _ledger(migrated_db) == []
    findings = _run(migrated_db)
    for criterion in (1, 3, 4, 5):
        assert findings[criterion].issues == NOT_AVAILABLE, criterion


SECRETS = (PLANT_DIR, PLANT_STEM, PLANT_DUP_STEM, "qorvex-clean", "qorvex-format", "/source")


def _main_detail(migrated_db: str, monkeypatch: pytest.MonkeyPatch, capsys: Any) -> Any:
    assert any(r.source_path.startswith(f"/source/{PLANT_DIR}/") for r in _ledger(migrated_db))
    monkeypatch.setenv("APP_DB_DSN", migrated_db)
    code = gate_4.main(["--detail"], engine=read_only_engine(migrated_db))
    out = capsys.readouterr()
    for secret in SECRETS:
        assert secret not in out.out and secret not in out.err
    assert "postgresql" not in out.out and "postgresql" not in out.err
    return code, out.out.splitlines()


def test_main_detail_without_the_ui_prints_hashes_and_codes_only(
    migrated_db, seed, ui, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ui(None)
    _seed_folder(seed)
    code, lines = _main_detail(migrated_db, monkeypatch, capsys)
    assert code == 1
    assert "gate 4 FAIL" in lines
    assert "gate 4 criterion 1 (every row reachable through /api/files): ok" in lines
    assert "  3 - NOT_AVAILABLE" in lines


def test_main_detail_with_the_ui_passes(
    migrated_db, seed, ui, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ui(StandIn())
    _seed_folder(seed)
    code, lines = _main_detail(migrated_db, monkeypatch, capsys)
    assert code == 0, lines
    assert lines[-1] == "gate 4 PASS" and len(lines) == len(gate_4.CRITERIA) + 1  # no detail


def test_main_detail_with_a_leak_prints_hashes_and_codes_only(
    migrated_db, seed, ui, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    ui(StandIn(leak_on="/ui/latest"))
    _, planted = _seed_folder(seed)
    code, lines = _main_detail(migrated_db, monkeypatch, capsys)
    assert code == 1
    assert f"  4 {planted[:8]} LEAK_PATH" in lines  # the plant was caught, then left out


def test_the_runner_reads_one_bounded_sse_frame(migrated_db, seed) -> None:
    _, planted = _seed_folder(seed)
    ledger, served = gate_4.serve(migrated_db, read_only_engine(migrated_db))
    assert any(r.source_hash == planted for r in ledger)  # the plant is held
    events = served.bodies["events"]
    assert events is not None and gate_4.STATUS_FRAME in events  # the stream ended on its own
    assert served.bodies["files"] is not None and planted[:8] in served.bodies["files"]
    for body in (events, served.bodies["status"], served.bodies["files"]):
        assert body is not None and PLANT_DIR not in body and PLANT_STEM not in body


def test_a_write_on_the_gates_engine_fails(migrated_db, seed) -> None:
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError

    planted = seed()
    engine = read_only_engine(migrated_db)
    try:
        with engine.connect() as conn:
            assert (
                conn.execute(
                    text("select count(*) from files where source_hash = :h"), {"h": planted}
                ).scalar_one()
                == 1
            )  # the row is there to be written
            with pytest.raises(DBAPIError):
                conn.execute(text("delete from files where source_hash = :h"), {"h": planted})
    finally:
        engine.dispose()
    assert any(r.source_hash == planted for r in _ledger(migrated_db))
