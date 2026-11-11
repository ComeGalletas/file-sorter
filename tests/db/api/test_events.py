"""API-001.2: `GET /api/events` through the app (acceptance test, tier db).

The route's sleep is swapped for a no-op and its ticks are bounded through `app.state`, so
`TestClient` gets a finite body and nothing really sleeps. The disconnect test drives the
unbounded stream through the raw ASGI interface instead. Rows are committed through their
own connection and deleted by hash in a `finally`, as in test_status_files.py. Privacy
plants (m4 item 11) are proved served or held before they are asserted absent.
"""

import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import psycopg
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from classifier.api.app import DB_UNAVAILABLE, create_app, read_only_engine
from classifier.api.events import KEEPALIVE
from classifier.config import Config, load_config

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config.yaml"
SECRET = "Zhyndel-planted-secret"
BASE = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)

Seed = Callable[..., str]


class _NoOllama:
    def loaded_models(self) -> None:
        return None


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


def _app(
    config: Config,
    engine: Engine,
    *,
    ticks: int | None,
    interval: float = 2.0,
    on_sleep: Callable[[], None] | None = None,
) -> FastAPI:
    app = create_app(config, engine=engine, ollama=_NoOllama())

    async def sleep(_seconds: float) -> None:
        if on_sleep is not None:
            on_sleep()
        await anyio.sleep(0)

    app.state.events_sleep = sleep
    app.state.events_interval = interval
    app.state.events_max_ticks = ticks
    return app


def _frames(body: bytes) -> list[bytes]:
    return [chunk + b"\n\n" for chunk in body.split(b"\n\n") if chunk]


def _status_data(frame: bytes) -> dict[str, Any]:
    event, data = frame.decode().strip().split("\n")
    assert event == "event: status"
    assert data.startswith("data: ")
    return json.loads(data[len("data: ") :])


def test_events_first_frame_is_the_status(config, engine) -> None:
    app = _app(config, engine, ticks=1)
    client = TestClient(app)
    response = client.get("/api/events")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert response.headers["x-accel-buffering"] == "no"
    [frame] = _frames(response.content)
    assert _status_data(frame) == client.get("/api/status").json()


def test_events_send_only_changes(config, engine, seed, tag) -> None:
    """Three ticks; a row lands during the first sleep only: two status frames."""
    landed: list[str] = []

    def on_sleep() -> None:
        if not landed:
            landed.append(seed(topic=tag, status="named"))

    response = TestClient(_app(config, engine, ticks=3, on_sleep=on_sleep)).get("/api/events")
    first, second = (_status_data(f) for f in _frames(response.content))
    assert second["counts_by_status"]["named"] == first["counts_by_status"]["named"] + 1
    assert any(c["topic"] == tag for c in second["grid"])
    assert not any(c["topic"] == tag for c in first["grid"])


def test_events_keepalive_after_15_s(config, engine) -> None:
    """API-001.D10 through the route: at 5 s per tick, the 3rd quiet tick (15 s) sends it."""
    response = TestClient(_app(config, engine, ticks=4, interval=5.0)).get("/api/events")
    frames = _frames(response.content)
    assert len(frames) == 2 and frames[1] == KEEPALIVE
    _status_data(frames[0])


def test_events_never_carry_paths_or_raw_names(config, engine, seed, tag) -> None:
    """m4 item 11: the planted row is proved in the stream first, then the secret is absent."""
    seed(
        topic=tag,
        status="named",
        raw_stem=f"{SECRET}-stem",
        duplicate_paths=[f"/source/{SECRET}-dup.png"],
        original_sanitized="qorvex-clean",
    )
    response = TestClient(_app(config, engine, ticks=1)).get("/api/events")
    [frame] = _frames(response.content)
    assert any(c["topic"] == tag for c in _status_data(frame)["grid"])  # proved served
    assert SECRET.encode() not in response.content
    assert b"/source" not in response.content
    assert all(SECRET not in f"{k}: {v}" for k, v in response.headers.items())


def _failing_engine() -> Engine:
    def creator() -> psycopg.Connection:
        raise psycopg.OperationalError(f"connection to {SECRET} failed")

    return create_engine("postgresql+psycopg://", creator=creator, poolclass=NullPool)


def test_events_unavailable_once_with_fixed_text(config, caplog) -> None:
    """API-001.D11: one fixed event for three failing ticks; the plant is held, not sent."""
    caplog.set_level(logging.DEBUG)
    dead = _failing_engine()
    try:
        with pytest.raises(SQLAlchemyError) as raw:
            dead.connect()
        assert SECRET in str(raw.value)
        caplog.clear()
        response = TestClient(_app(config, dead, ticks=3)).get("/api/events")
    finally:
        dead.dispose()
    assert response.status_code == 200
    detail = json.dumps({"detail": DB_UNAVAILABLE})
    assert _frames(response.content) == [f"event: unavailable\ndata: {detail}\n\n".encode()]
    assert SECRET.encode() not in response.content
    logged = caplog.text + "".join(repr(r.args) + str(r.exc_info) for r in caplog.records)
    assert SECRET not in logged and "Traceback" not in logged


def test_events_end_on_client_disconnect(config, engine) -> None:
    """The unbounded stream (no tick limit) ends once the client disconnects."""
    app = _app(config, engine, ticks=None)
    sent: list[dict[str, Any]] = []
    requests = 0

    async def receive() -> dict[str, Any]:
        nonlocal requests
        requests += 1
        if requests == 1:
            return {"type": "http.request", "body": b"", "more_body": False}
        while not any(m.get("body") for m in sent):  # disconnect after the first frame
            await anyio.sleep(0.01)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/events",
        "raw_path": b"/api/events",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"testserver")],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
        "state": {},
    }

    async def main() -> None:
        with anyio.fail_after(10):  # a stream that ignored the disconnect would hang here
            await app(scope, receive, send)

    anyio.run(main)
    assert sent[0]["type"] == "http.response.start" and sent[0]["status"] == 200
    bodies = [m.get("body", b"") for m in sent if m["type"] == "http.response.body"]
    assert bodies and bodies[0].startswith(b"event: status\n")
