"""API-001.4: the dashboard and the review queue over a migrated test schema (acceptance).

Rows are committed through their own connection and deleted by hash in a `finally`, as in
tests/db/api/test_status_files.py, because the app reads through its read-only engine. Every
synthetic name is a coinage. Seeded rows are dated far in the future, so they are the newest
whatever else the session committed. Privacy plants (m4 items 4, 11) are proved served by
each route before they are asserted absent from its body and headers.
"""

import hashlib
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from sqlalchemy import Engine

from classifier.api.app import INVALID_QUERY, create_app, read_only_engine
from classifier.api.views import ADULT_BRANCH, PER_PAGE
from classifier.config import Config, load_config
from classifier.models.classify_rules import UNSORTED
from classifier.ui.routes import CSP

ROOT = Path(__file__).resolve().parents[3]
SECRET = "Zhyndel-planted-secret"
FUTURE = datetime(2098, 1, 1, 0, 0, tzinfo=UTC)
FRAGMENTS = ("/ui/banner", "/ui/grid", "/ui/latest", "/ui/errors?page=1", "/ui/review?page=1")
STATIC = ("/", "/ui/app.js")
WRITE_MARKERS = ("<form", "<button", "hx-post", "hx-put", "hx-patch", "hx-delete", "method=")
THUMB = re.compile(
    r'<img class="thumb" src="/thumbs/([0-9a-f]{64})" data-hash="([0-9a-f]{8})" '
    r'data-blur="([01])" alt="">'
)

Seed = Callable[..., str]


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config(ROOT / "config.yaml")


@pytest.fixture
def engine(migrated_db: str) -> Iterator[Engine]:
    eng = read_only_engine(migrated_db)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture
def client(config: Config, engine: Engine) -> TestClient:
    return TestClient(create_app(config, engine=engine, ollama=None))


@pytest.fixture
def tag() -> str:
    return f"Qorvex{uuid.uuid4().hex[:10]}"


@pytest.fixture
def seed(migrated_db: str) -> Iterator[Seed]:
    """Insert committed synthetic rows; delete them by hash at teardown, whatever happens."""
    hashes: list[str] = []
    conn = psycopg.connect(migrated_db, autocommit=True)

    def add(**cols: Any) -> str:
        source_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        stem = cols.pop("raw_stem", "qorvex-raw")
        row: dict[str, Any] = {
            "source_hash": source_hash,
            "short_hash": source_hash[:8],
            "source_path": f"/source/{stem}.png",
            "source_mtime": FUTURE,
            "ext": "png",
            "status": "classified",
            "updated_at": FUTURE,
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


def _get(client: TestClient, path: str) -> Any:
    response = client.get(path)
    assert response.status_code == 200, (path, response.status_code)
    return response


def _row(body: str, source_hash: str) -> str:
    match = re.search(rf'<tr data-hash="{source_hash[:8]}"[^\n]*</tr>', body)
    assert match is not None, "row not served"
    return match.group(0)


def _headers_text(response: Any) -> str:
    return "\n".join(f"{k}: {v}" for k, v in response.headers.items())


# --- privacy: plants proved served, then absent ---------------------------------------------


def test_planted_secrets_never_reach_any_ui_route(client, seed, tag) -> None:
    h = seed(
        raw_stem=SECRET,
        duplicate_paths=[f"/source/dup/{SECRET}.png"],
        caption=Jsonb({"text": SECRET}),
        proposed_path=f"/results/{SECRET}.png",
        output_path=f"/results/out/{SECRET}.png",
        template=SECRET,
        original_sanitized="qorvex-sanitized",
        topic=tag,
        format="Zhyndelform",
        needs_review=True,
        review_reason="unsorted",
        error="E_QORVEX",
        updated_at=FUTURE + timedelta(days=1),
    )
    bodies = {path: _get(client, path) for path in FRAGMENTS + STATIC}
    # Proved served first: each fragment carries the planted row.
    for path in ("/ui/latest", "/ui/review?page=1"):
        row = _row(bodies[path].text, h)
        assert "qorvex-sanitized.png" in row and tag in row
    assert _row(bodies["/ui/errors?page=1"].text, h).count("E_QORVEX") == 1
    assert h[:8] in bodies["/ui/banner"].text  # the last error
    assert tag in bodies["/ui/grid"].text
    for path, response in bodies.items():
        assert SECRET not in response.text, path
        assert SECRET not in _headers_text(response), path
        assert "/source" not in response.text and "/results" not in response.text, path


# --- escaping -------------------------------------------------------------------------------


def test_every_value_is_escaped(client, seed, tag) -> None:
    h = seed(
        original_sanitized='"><script>alert(1)</script>',
        format='Zhyndel" onmouseover="x',
        topic=f"{tag}<b>",
        error="<i>E</i>",
        needs_review=True,
        review_reason="unsorted",
    )
    for path in FRAGMENTS:
        body = _get(client, path).text
        lowered = body.lower()
        for bad in ("<script", 'onmouseover="', "<b>", "<i>"):
            assert bad not in lowered, (path, bad)
    review = _row(_get(client, "/ui/review?page=1").text, h)
    assert "&quot;&gt;&lt;script&gt;alert(1)&lt;/script&gt;.png" in review
    assert "Zhyndel&quot; onmouseover=&quot;x" in review and f"{tag}&lt;b&gt;" in review
    assert "&lt;i&gt;E&lt;/i&gt;" in _row(_get(client, "/ui/errors?page=1").text, h)
    assert f"{tag}&lt;b&gt;" in _get(client, "/ui/grid").text


# --- API-001.D8: the blur flag, server-side ---------------------------------------------------


def test_adult_thumbs_are_blurred_by_default(client, seed, tag) -> None:
    rows = {
        "1": seed(topic=tag, branch=ADULT_BRANCH, needs_review=True, review_reason="unsorted"),
        "0": seed(topic=tag, branch="safe", needs_review=True, review_reason="unsorted"),
    }
    none = seed(
        topic=tag, branch=None, status="queued", needs_review=True, review_reason="unsorted"
    )
    for path in ("/ui/latest", "/ui/review?page=1"):
        body = _get(client, path).text
        for blur, h in [*rows.items(), ("0", none)]:
            [match] = THUMB.findall(_row(body, h))
            assert match == (h, h[:8], blur), path


# --- API-001.D9: the review queue -------------------------------------------------------------


def test_review_queue_membership(client, seed, tag) -> None:
    flagged = seed(
        topic=tag,
        format="Zhyndelform",
        original_sanitized="qorvex-flagged",
        nsfw_level="suggestive",
        nsfw_traces=False,
        needs_review=True,
        review_reason="nsfw_disagreement",
    )
    unsorted = seed(topic=tag, format=UNSORTED, needs_review=False)
    plain = seed(topic=tag, format="Zhyndelform", needs_review=False)
    body = _get(client, "/ui/review?page=1").text
    row = _row(body, flagged)
    assert f'data-source-hash="{flagged}"' in row
    # The full cell run, position by position: hash, name, format, topic, NSFW level,
    # traces, the cross-check flag, the review reason.
    cells = (
        f"<td>{flagged[:8]}</td><td>qorvex-flagged.png</td><td>Zhyndelform</td><td>{tag}</td>"
        "<td>suggestive</td><td>no</td><td>yes</td><td>nsfw_disagreement</td></tr>"
    )
    assert row.endswith(cells)
    _row(body, unsorted)
    assert f'data-hash="{plain[:8]}"' not in body


def test_review_queue_pages_newest_first(client, seed, tag) -> None:
    hashes = [
        seed(
            topic=tag,
            needs_review=True,
            review_reason="unsorted",
            updated_at=FUTURE - timedelta(minutes=i),
        )
        for i in range(PER_PAGE + 1)
    ]
    page1 = _get(client, "/ui/review?page=1").text
    served = re.findall(r'<tr data-hash="[0-9a-f]{8}" data-source-hash="([0-9a-f]{64})"', page1)
    assert served == hashes[:PER_PAGE]
    # API-001.D14: the last row loads page 2, through a same-origin path and a link only.
    more = re.findall(r'<tr class="more" data-more="([^"]*)">(.*?)</tr>', page1)
    assert more == [("/ui/review?page=2", '<td colspan="9"><a href="#">more</a></td>')]
    assert page1.endswith("</tr>\n") and page1.count('class="more"') == 1
    for marker in WRITE_MARKERS:
        assert marker not in page1.lower(), marker  # the more row is no form or button
    page2 = _get(client, "/ui/review?page=2").text
    assert re.findall(r'data-source-hash="([0-9a-f]{64})"', page2)[0] == hashes[PER_PAGE]
    assert _get(client, "/ui/review?page=100000").text == ""  # past the end: empty


@pytest.mark.parametrize("page", ["0", "-1", "x", "1000001"])
def test_bad_page_is_a_fixed_422(client, page: str) -> None:
    for route in ("/ui/review", "/ui/errors"):
        response = client.get(route, params={"page": page})
        assert response.status_code == 422
        assert response.json() == {"detail": INVALID_QUERY}


# --- latest and errors ----------------------------------------------------------------------


def test_latest_is_twenty_rows_newest_first(client, seed, tag) -> None:
    hashes = [seed(topic=tag, updated_at=FUTURE - timedelta(minutes=i)) for i in range(25)]
    body = _get(client, "/ui/latest").text
    served = re.findall(r'<tr data-hash="([0-9a-f]{8})"', body)
    assert served == [h[:8] for h in hashes[:20]]


def test_errors_show_code_and_no_retry(client, seed, tag) -> None:
    h = seed(topic=tag, status="error", error="E_ZHYNDEL")
    row = _row(_get(client, "/ui/errors?page=1").text, h)
    assert f"<td>{h[:8]}</td><td>error</td><td>E_ZHYNDEL</td>" in row
    assert "retry" not in _get(client, "/").text.lower()


# --- no outbound reference, read-only, headers ------------------------------------------------


def test_no_outbound_reference(client, seed, tag) -> None:
    seed(topic=tag, needs_review=True, review_reason="unsorted")
    for path in FRAGMENTS + ("/",):
        body = _get(client, path).text
        assert tag in body or path in ("/", "/ui/banner", "/ui/errors?page=1"), path
        assert not re.search(r"https?:|//", body), path
    js = _get(client, "/ui/app.js").text
    assert "http:" not in js and "https:" not in js
    assert not re.search(r"""["'(`]\s*//""", js)  # no protocol-relative URL in a literal
    srcs = re.findall(r'(?:src|href)="([^"]*)"', _get(client, "/").text)
    assert srcs == ["/ui/app.js"]  # DOC-016.D3: the only script, no third-party library


def test_ui_is_read_only(client, seed, tag) -> None:
    seed(topic=tag, needs_review=True, review_reason="unsorted")
    for path in FRAGMENTS + ("/",):
        lowered = _get(client, path).text.lower()
        for marker in WRITE_MARKERS:
            assert marker not in lowered, (path, marker)
    for path in FRAGMENTS + STATIC:
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, path).status_code == 405, (method, path)


def test_no_htmx_is_served(client, seed, tag) -> None:
    """DOC-016.D3: no hx- attribute or htmx reference anywhere, and no vendor route."""
    seed(topic=tag, needs_review=True, review_reason="unsorted")
    for path in FRAGMENTS + STATIC:
        lowered = _get(client, path).text.lower()
        assert "hx-" not in lowered and "htmx" not in lowered, path
    response = client.get("/ui/vendor/htmx.min.js")
    assert response.status_code == 404
    assert response.json() == {"detail": "not found"}


def test_the_page_names_each_fragment_and_its_group(client) -> None:
    """DOC-016.D3, API-001.D15: the five fragments, each a same-origin GET route, in two
    refresh groups; `app.js` loads every `data-fragment` and refreshes by group."""
    page = _get(client, "/").text
    sections = re.findall(r'data-fragment="([^"]*)" data-group="([^"]*)"', page)
    assert page.count("data-fragment=") == len(sections)  # every one carries a group
    assert sorted(sections) == sorted(
        [
            ("/ui/banner", "refresh"),
            ("/ui/grid", "refresh"),
            ("/ui/latest", "refresh"),
            ("/ui/errors?page=1", "refresh-queue"),
            ("/ui/review?page=1", "refresh-queue"),
        ]
    )
    assert tuple(route for route, _ in sections) == FRAGMENTS
    for route, _ in sections:
        response = _get(client, route)
        assert response.headers["content-security-policy"] == CSP, route
    js = _get(client, "/ui/app.js").text
    for marker in (
        '"[data-fragment]"',
        'getAttribute("data-fragment")',
        'refresh("refresh")',
        'refresh("refresh-queue")',
        'addEventListener("status"',
        'credentials: "same-origin"',
        'redirect: "error"',
        # API-001.D14: the "more" rows, on scrolling into view or a click.
        "new IntersectionObserver(",
        '"tr.more[data-more]"',
        'getAttribute("data-more")',
        "event.preventDefault()",
    ):
        assert marker in js, marker


def test_csp_is_the_d13_literal(client) -> None:
    """API-001.D13, typed out here so a change to `routes.CSP` can't pass unnoticed."""
    want = (
        "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
        "frame-ancestors 'none'"
    )
    for path in FRAGMENTS + STATIC:
        assert _get(client, path).headers["content-security-policy"] == want, path


def test_security_headers_on_every_ui_response(client) -> None:
    for path in FRAGMENTS + STATIC:
        headers = _get(client, path).headers
        assert headers["content-security-policy"] == CSP, path
        assert headers["referrer-policy"] == "no-referrer"
        assert headers["x-content-type-options"] == "nosniff"
    assert _get(client, "/").headers["content-type"].startswith("text/html")
    assert _get(client, "/ui/app.js").headers["content-type"].startswith("text/javascript")
