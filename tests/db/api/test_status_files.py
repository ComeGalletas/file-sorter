"""API-001.1: `/api/files` and `/api/status` over a migrated test schema (acceptance test).

The app reads through its own read-only engine, so it can't see the rolled-back `db`
fixture's transaction. Rows are committed through their own connection instead, and the
`seed` fixture deletes them by hash in a `finally`. Every synthetic name is a coinage, and a
unique run tag keeps each test's filters to its own rows. Privacy plants (m4 item 11) are
proved served before they are asserted absent.
"""

import hashlib
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from classifier.api.app import DB_UNAVAILABLE, INVALID_QUERY, create_app, read_only_engine
from classifier.api.views import FILE_ROW_FIELDS, PER_PAGE
from classifier.config import Config, load_config

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config.yaml"
SECRET = "Zhyndel-planted-secret"
BASE = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

Seed = Callable[..., str]


@pytest.fixture(scope="module")
def config() -> Config:
    return load_config(CONFIG)


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


def _client(config: Config, engine: Engine, ollama: Any = None) -> TestClient:
    return TestClient(create_app(config, engine=engine, ollama=ollama))


def _files(client: TestClient, **params: Any) -> dict[str, Any]:
    response = client.get("/api/files", params=params)
    assert response.status_code == 200, response.status_code
    return response.json()


# --- /api/files ---------------------------------------------------------------------------


def test_files_row_has_exactly_the_contract_fields(config, engine, seed, tag) -> None:
    h = seed(topic=tag, original_sanitized="qorvex-stem", review_reason="nsfw_disagreement")
    body = _files(_client(config, engine), topic=tag)
    assert body["total"] == 1 and body["page"] == 1 and body["per_page"] == PER_PAGE
    [row] = body["rows"]
    assert tuple(row) == FILE_ROW_FIELDS
    assert row["source_hash"] == h and row["short_hash"] == h[:8]
    assert row["sanitized_name"] == "qorvex-stem.png"
    assert row["cross_check_disagrees"] is True


def test_files_null_sanitized_name_before_sanitize(config, engine, seed, tag) -> None:
    seed(topic=tag, status="queued")
    [row] = _files(_client(config, engine), topic=tag)["rows"]
    assert row["sanitized_name"] is None


def test_files_filters_combine_with_and(config, engine, seed, tag) -> None:
    want = seed(topic=tag, format="Zhyndelform", status="classified", needs_review=True)
    seed(topic=tag, format="Zhyndelform", status="classified", needs_review=False)
    seed(topic=tag, format="Vorlathform", status="classified", needs_review=True)
    seed(topic=tag, format="Zhyndelform", status="error", needs_review=True)
    client = _client(config, engine)
    assert _files(client, topic=tag)["total"] == 4
    body = _files(client, topic=tag, format="Zhyndelform", status="classified", needs_review="true")
    assert [r["source_hash"] for r in body["rows"]] == [want]


def test_files_paging_newest_first(config, engine, seed, tag) -> None:
    hashes = [seed(topic=tag, updated_at=BASE + timedelta(minutes=i)) for i in range(PER_PAGE + 3)]
    client = _client(config, engine)
    first = _files(client, topic=tag)
    second = _files(client, topic=tag, page=2)
    assert first["total"] == second["total"] == PER_PAGE + 3
    assert len(first["rows"]) == PER_PAGE and len(second["rows"]) == 3
    served = [r["source_hash"] for r in first["rows"] + second["rows"]]
    assert served == list(reversed(hashes))
    assert _files(client, topic=tag, page=3)["rows"] == []


@pytest.mark.parametrize(
    "params",
    [
        {"status": "Qorvexstatus"},
        {"page": "0"},
        {"page": "-1"},
        {"page": "Qorvexpage"},
        {"page": "99999999999999999999"},
        {"needs_review": "Qorvexbool"},
    ],
)
def test_files_bad_input_is_a_fixed_422(config, engine, params) -> None:
    response = _client(config, engine).get("/api/files", params=params)
    assert response.status_code == 422
    assert response.json() == {"detail": INVALID_QUERY}
    assert "Qorvex" not in response.text


def test_files_never_serve_paths_or_raw_names(config, engine, seed, tag, migrated_db) -> None:
    """m4 item 11: the planted row is served first, then the secret is absent."""
    h = seed(
        topic=tag,
        raw_stem=f"{SECRET}-stem",
        duplicate_paths=[f"/source/{SECRET}-dup.png"],
        original_sanitized="qorvex-clean",
    )
    with psycopg.connect(migrated_db) as conn:  # the plant is really held by the ledger
        path, dups = conn.execute(
            "select source_path, duplicate_paths from files where source_hash = %s", [h]
        ).fetchone()
    assert SECRET in path and SECRET in dups[0]
    response = _client(config, engine).get("/api/files", params={"topic": tag})
    assert response.status_code == 200
    assert [r["source_hash"] for r in response.json()["rows"]] == [h]  # proved served
    assert SECRET not in response.text
    assert all(SECRET not in f"{k}: {v}" for k, v in response.headers.items())
    assert "/source" not in response.text


# --- the session and errors --------------------------------------------------------------


def test_app_engine_is_read_only(config, engine) -> None:
    app = create_app(config, engine=engine)
    with pytest.raises(DBAPIError) as caught, app.state.engine.connect() as conn:
        conn.execute(
            text(
                "insert into files (source_hash, short_hash, source_path, source_mtime, ext)"
                " values ('x', 'x', 'x', now(), 'x')"
            )
        )
    assert "read-only" in str(caught.value.orig)


def test_db_failure_is_a_fixed_503(config) -> None:
    dead = read_only_engine(f"postgresql://qorvex:{SECRET}@127.0.0.1:1/qorvex")
    try:
        response = TestClient(create_app(config, engine=dead)).get(
            "/api/files", params={"topic": SECRET}
        )
    finally:
        dead.dispose()
    assert response.status_code == 503
    assert response.json() == {"detail": DB_UNAVAILABLE}
    assert SECRET not in response.text


def test_access_log_is_off(config, engine) -> None:
    import logging

    create_app(config, engine=engine)
    assert logging.getLogger("uvicorn.access").disabled is True
