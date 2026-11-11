"""API-001.3: `GET /thumbs/{source_hash}` through the app (acceptance test, tier db).

The config's `results_root` is a `tmp_path` holding synthetic webp thumbnails. Ledger rows
are committed through their own connection and deleted by hash in a `finally`. Every
refusal is the same fixed 404 (API-001.D12), and each refusal's plant is proved present or
readable first, so the 404 could have been a 200 (m4 privacy item 13).
"""

import hashlib
import io
import logging
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Engine, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from classifier.api import thumbs
from classifier.api.app import DB_UNAVAILABLE, NOT_FOUND, create_app, read_only_engine
from classifier.api.views import ADULT_BRANCH
from classifier.config import Config, load_config

ROOT = Path(__file__).resolve().parents[3]
CONFIG = ROOT / "config.yaml"
SECRET = "Zhyndel-planted-secret"
BASE = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
MISS = {"detail": NOT_FOUND}

Seed = Callable[..., str]


class _NoOllama:
    def loaded_models(self) -> None:
        return None


def _webp(color: tuple[int, int, int] = (40, 90, 160)) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), color).save(out, format="WEBP")
    return out.getvalue()


@pytest.fixture
def results(tmp_path: Path) -> Path:
    (tmp_path / "results" / ".work" / "thumbs").mkdir(parents=True)
    return tmp_path / "results"


@pytest.fixture
def config(results: Path) -> Config:
    cfg = load_config(CONFIG).model_copy(deep=True)
    cfg.paths.results_root = str(results)
    return cfg


@pytest.fixture
def engine(migrated_db: str) -> Iterator[Engine]:
    eng = read_only_engine(migrated_db)
    try:
        yield eng
    finally:
        eng.dispose()


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


def _client(config: Config, engine: Engine) -> TestClient:
    return TestClient(create_app(config, engine=engine, ollama=_NoOllama()))


def _thumb(results: Path, source_hash: str) -> Path:
    return results / ".work" / "thumbs" / f"{source_hash}.webp"


def _assert_miss(response: Any) -> None:
    assert response.status_code == 404
    assert response.json() == MISS


def test_serves_the_ledger_rows_thumbnail(config, engine, seed, results) -> None:
    h = seed()
    data = _webp()
    _thumb(results, h).write_bytes(data)
    response = _client(config, engine).get(f"/thumbs/{h}")
    assert response.status_code == 200
    assert response.content == data
    assert response.headers["content-type"] == "image/webp"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "private, no-store"


def test_adult_rows_get_the_same_bytes(config, engine, seed, results) -> None:
    """The blur is the UI's job (API-001.4); the route serves the bytes unchanged."""
    h = seed(branch=ADULT_BRANCH)
    data = _webp((200, 30, 30))
    _thumb(results, h).write_bytes(data)
    assert _client(config, engine).get(f"/thumbs/{h}").content == data


def test_a_file_not_in_the_ledger_is_a_miss(config, engine, results) -> None:
    """The plant is readable by the reader itself, so only the ledger check refuses it."""
    h = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
    _thumb(results, h).write_bytes(_webp())
    assert thumbs.read_thumbnail(results, h) is not None
    _assert_miss(_client(config, engine).get(f"/thumbs/{h}"))


def test_a_row_with_no_file_is_a_miss(config, engine, seed) -> None:
    _assert_miss(_client(config, engine).get(f"/thumbs/{seed()}"))


def test_a_symlinked_thumbnail_is_a_miss(config, engine, seed, results, tmp_path) -> None:
    h = seed()
    target = tmp_path / "elsewhere.webp"
    target.write_bytes(_webp())
    _thumb(results, h).symlink_to(target)
    assert _thumb(results, h).read_bytes() == target.read_bytes()  # the link works
    _assert_miss(_client(config, engine).get(f"/thumbs/{h}"))


def test_a_non_regular_file_is_a_miss(config, engine, seed, results) -> None:
    h = seed()
    _thumb(results, h).mkdir()
    assert _thumb(results, h).exists()
    _assert_miss(_client(config, engine).get(f"/thumbs/{h}"))


@pytest.mark.parametrize(
    "path",
    [
        "/thumbs/" + "A" * 64,
        "/thumbs/" + "a" * 63,
        "/thumbs/" + "a" * 65,
        "/thumbs/..%2F..%2F" + SECRET,
        "/thumbs/%2e%2e%2f" + SECRET,
        "/thumbs/" + SECRET,
        "/thumbs/a/" + SECRET,  # no route matches: the same fixed 404
    ],
)
def test_bad_shapes_are_the_same_fixed_miss(config, engine, seed, results, path) -> None:
    h = seed()
    _thumb(results, h).write_bytes(_webp())  # a real thumbnail sits in the folder
    response = _client(config, engine).get(path)
    _assert_miss(response)
    assert SECRET not in response.text
    assert all(SECRET not in f"{k}: {v}" for k, v in response.headers.items())


def test_an_oserror_is_a_miss_with_nothing_kept(
    config, engine, seed, results, monkeypatch, caplog
) -> None:
    caplog.set_level(logging.DEBUG)
    h = seed()
    _thumb(results, h).write_bytes(_webp())
    client = _client(config, engine)
    assert client.get(f"/thumbs/{h}").status_code == 200  # served before the fault
    error = PermissionError(13, SECRET, f"/results/{SECRET}")
    assert SECRET in str(error)

    def refuse(*_args: object, **_kwargs: object) -> int:
        raise error

    monkeypatch.setattr(thumbs.os, "open", refuse)
    caplog.clear()
    response = client.get(f"/thumbs/{h}")
    _assert_miss(response)
    assert SECRET not in response.text
    logged = caplog.text + "".join(repr(r.args) + str(r.exc_info) for r in caplog.records)
    assert SECRET not in logged and "Traceback" not in logged


def _failing_engine() -> Engine:
    def creator() -> psycopg.Connection:
        raise psycopg.OperationalError(f"connection to {SECRET} failed")

    return create_engine("postgresql+psycopg://", creator=creator, poolclass=NullPool)


def test_a_database_failure_is_the_fixed_503(config, results) -> None:
    h = hashlib.sha256(b"qorvex").hexdigest()
    _thumb(results, h).write_bytes(_webp())
    dead = _failing_engine()
    try:
        with pytest.raises(SQLAlchemyError) as raw:
            dead.connect()
        assert SECRET in str(raw.value)
        response = TestClient(create_app(config, engine=dead, ollama=_NoOllama())).get(
            f"/thumbs/{h}"
        )
    finally:
        dead.dispose()
    assert response.status_code == 503
    assert response.json() == {"detail": DB_UNAVAILABLE}
    assert SECRET not in response.text


def test_an_unknown_api_route_is_the_same_fixed_miss(config, engine) -> None:
    _assert_miss(_client(config, engine).get(f"/api/{SECRET}"))
