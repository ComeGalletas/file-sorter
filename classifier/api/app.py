"""API-001.1: the read-only FastAPI app (R-API-1, R-API-2).

`create_app(config, *, engine=None, ollama=None)` is the factory the plan fixes (m4,
"Contracts fixed here"). Every database read runs on a read-only session. Nothing is logged
per request: the uvicorn access log is off (m4 privacy item 15), and errors carry fixed text
only, so neither a filter value (a category name) nor a SQL parameter reaches a log line or a
response body.
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Annotated, Any, TypeVar

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from classifier.api.views import (
    FileFilters,
    FilePage,
    ModelProbe,
    build_file_page,
)
from classifier.config import Config
from classifier.db.models import FileStatus
from classifier.db.url import to_sqlalchemy_url

INVALID_QUERY = "invalid query"  # API-001.D5: fixed text, never the input echoed back
DB_UNAVAILABLE = "database unavailable"
NO_DSN = "the database DSN is not set"
MAX_PAGE = 1_000_000  # keeps the offset far inside bigint

T = TypeVar("T")


def _set_read_only(dbapi_conn: Any, _record: Any) -> None:
    """Every transaction on this connection is READ ONLY (API-001.1, R-API-2 is read-only)."""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("set session characteristics as transaction read only")
    finally:
        cur.close()
    dbapi_conn.commit()


def make_read_only(engine: Engine) -> Engine:
    if not event.contains(engine, "connect", _set_read_only):
        event.listen(engine, "connect", _set_read_only)
    return engine


def read_only_engine(dsn: str) -> Engine:
    """A NullPool engine whose sessions are read-only; SQL parameters stay out of errors."""
    engine = create_engine(to_sqlalchemy_url(dsn), poolclass=NullPool, hide_parameters=True)
    return make_read_only(engine)


class _LazyOllama:
    """The real client, built on first use; any failure there reads as "n/a"."""

    def __init__(self) -> None:
        self._client: Any = None
        self._failed = False

    def loaded_models(self) -> Any:
        if self._client is None and not self._failed:
            try:
                from classifier.models.ollama import OllamaClient

                self._client = OllamaClient.from_env()
            except Exception:  # e.g. OLLAMA_HOST unset: no text kept
                self._failed = True
        if self._client is None:
            return None
        return self._client.loaded_models()


def create_app(
    config: Config, *, engine: Engine | None = None, ollama: ModelProbe | None = None
) -> FastAPI:
    if engine is None:
        if not config.db.dsn:
            raise ValueError(NO_DSN)
        engine = read_only_engine(config.db.dsn)
    else:
        engine = make_read_only(engine)
    probe: ModelProbe = ollama if ollama is not None else _LazyOllama()

    # m4 item 15: no request line is ever logged (CLI-008's serve also passes access_log=False).
    logging.getLogger("uvicorn.access").disabled = True

    app = FastAPI(title="file-sorter", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, _exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body echoes the input, which can be a category name.
        return JSONResponse(status_code=422, content={"detail": INVALID_QUERY})

    @contextmanager
    def _connection() -> Iterator[Connection]:
        with engine.connect() as conn:
            conn.execute(text("set transaction read only"))
            yield conn

    def _read(fn: Callable[[Connection], T]) -> T:
        failed = False
        try:
            with _connection() as conn:
                return fn(conn)
        except SQLAlchemyError:
            failed = True
        if failed:  # raised outside the except block: no __cause__, no __context__
            raise HTTPException(status_code=503, detail=DB_UNAVAILABLE)
        raise AssertionError("unreachable")

    @app.get("/api/files", response_model=FilePage)
    def api_files(
        status: FileStatus | None = None,
        format: str | None = None,
        topic: str | None = None,
        needs_review: bool | None = None,
        page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    ) -> FilePage:
        filters = FileFilters(status=status, format=format, topic=topic, needs_review=needs_review)
        return _read(lambda conn: build_file_page(conn, filters, page))

    app.state.engine = engine
    app.state.probe = probe
    return app
