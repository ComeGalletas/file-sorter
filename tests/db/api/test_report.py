"""API-001.5: `render_report` over real ledger rows, through API-001.1's views (acceptance).

Rows are committed through their own connection and deleted by hash in a `finally`, as in
tests/db/api/test_status_files.py, because the views read through the read-only engine. Every
synthetic name is a coinage. Privacy plants (m4 items 4, 11) are proved served before they
are asserted absent.
"""

import hashlib
import re
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from sqlalchemy import Engine

from classifier.api.app import read_only_engine
from classifier.api.report import render_report
from classifier.api.views import ADULT_BRANCH, FileFilters, build_status, file_row, rows_query

SECRET = "Zhyndel-planted-secret"
BASE = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

Seed = Callable[..., str]


@pytest.fixture
def engine(migrated_db: str) -> Iterator[Engine]:
    eng = read_only_engine(migrated_db)
    try:
        yield eng
    finally:
        eng.dispose()


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
            "source_mtime": BASE,
            "ext": "png",
            "status": "classified",
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


def _report(engine: Engine) -> tuple[str, int]:
    """The report over the whole ledger, rows streamed once; and how many rows it was given."""
    seen = 0
    with engine.connect() as conn:
        status = build_status(conn)

        def rows() -> Iterator[Any]:
            nonlocal seen
            for m in conn.execute(rows_query(FileFilters())).mappings():
                seen += 1
                yield file_row(m)

        html = render_report(status, rows())
    return html, seen


def _section(html: str, heading: str) -> str:
    start = html.index(f"<h2>{heading}</h2>")
    end = html.find("<h2>", start + 1)
    return html[start : end if end != -1 else len(html)]


def _row(html: str, source_hash: str) -> str:
    match = re.search(rf'<tr data-hash="{source_hash[:8]}"[^\n]*</tr>', html)
    assert match is not None, "row not in report"
    return match.group(0)


def test_planted_secrets_never_reach_the_report(engine, seed, tag) -> None:
    h = seed(
        raw_stem=SECRET,
        duplicate_paths=[f"/source/dup/{SECRET}.png"],
        caption=Jsonb({"text": SECRET}),
        proposed_path=f"/results/{SECRET}.png",
        output_path=f"/results/out/{SECRET}.png",
        template=SECRET,
        original_sanitized="qorvex-sanitized",
        topic=tag,
    )
    html, _ = _report(engine)
    # Proved served first: the planted row is in the report, with its sanitized name.
    row = _row(html, h)
    assert "qorvex-sanitized.png" in row and tag in row
    assert SECRET not in html
    assert "/source" not in html and "/results" not in html


def test_every_value_is_escaped(engine, seed, tag) -> None:
    h = seed(
        original_sanitized="<script>alert(1)</script>",
        format='Zhyndel" onmouseover="x',
        topic=f"{tag}<b>",
    )
    html, _ = _report(engine)
    row = _row(html, h)
    assert "&lt;script&gt;alert(1)&lt;/script&gt;.png" in row
    assert "Zhyndel&quot; onmouseover=&quot;x" in row
    assert f"{tag}&lt;b&gt;" in row
    lowered = html.lower()
    for bad in ("<script", 'onmouseover="', "<b>", "<img", "src=", "href=", "<link"):
        assert bad not in lowered, bad


def test_no_outbound_reference(engine, seed, tag) -> None:
    seed(topic=tag, format="https://qorvex.example/x", original_sanitized="//zhyndel")
    html, _ = _report(engine)
    assert tag in html  # served
    # The planted values are escaped text in a page whose CSP refuses every load ...
    assert "default-src 'none'" in html
    # ... and the page itself makes no reference: strip the planted text, then scan.
    rest = html.replace("https://qorvex.example/x", "").replace("//zhyndel", "")
    assert not re.search(r"https?:|//", rest)


def test_adult_split_uses_is_adult(engine, seed, tag) -> None:
    adult = seed(topic=f"{tag}a", format="Zhyndelform", branch=ADULT_BRANCH)
    safe = seed(topic=f"{tag}s", format="Zhyndelform", branch="safe")
    unclassified = seed(topic=f"{tag}n", format="Zhyndelform", branch=None, status="queued")
    html, _ = _report(engine)

    adult_grid = _section(html, "Topic × format: adult")
    safe_grid = _section(html, "Topic × format: safe")
    none_grid = _section(html, "Topic × format: not classified")
    assert f"{tag}a<" in adult_grid
    assert f"{tag}a<" not in safe_grid and f"{tag}a<" not in none_grid
    assert f"{tag}s<" in safe_grid
    assert f"{tag}s<" not in adult_grid and f"{tag}s<" not in none_grid
    assert f"{tag}n<" in none_grid
    assert f"{tag}n<" not in adult_grid and f"{tag}n<" not in safe_grid

    assert 'class="adult"' in _row(html, adult) and "<td>adult</td>" in _row(html, adult)
    assert 'class="adult"' not in _row(html, safe) and "<td>safe</td>" in _row(html, safe)
    row = _row(html, unclassified)
    assert 'class="adult"' not in row and "<td>not classified</td>" in row


def test_every_ledger_row_is_in_the_report(engine, seed, tag) -> None:
    hashes = [seed(topic=tag, updated_at=BASE.replace(minute=i)) for i in range(7)]
    html, seen = _report(engine)
    assert seen >= len(hashes)
    assert html.count("<tr data-hash=") == seen
    for h in hashes:
        _row(html, h)
    # Newest first, as the caller's query orders them.
    positions = [html.index(f'data-hash="{h[:8]}"') for h in hashes]
    assert positions == sorted(positions, reverse=True)
