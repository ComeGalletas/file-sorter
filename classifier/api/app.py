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
from typing import Annotated, Any

import anyio
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import Connection, Engine, create_engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.pool import NullPool

from classifier.api.events import status_events
from classifier.api.views import (
    FileFilters,
    FilePage,
    ModelProbe,
    StatusView,
    build_file_page,
    build_status,
    with_loaded_models,
)
from classifier.config import Config
from classifier.db.models import FileStatus
from classifier.db.url import to_sqlalchemy_url

INVALID_QUERY = "invalid query"  # API-001.D5: fixed text, never the input echoed back
DB_UNAVAILABLE = "database unavailable"
INTERNAL_ERROR = "internal error"
NO_DSN = "the database DSN is not set"
BAD_DSN = "the database DSN is malformed"
MAX_PAGE = 1_000_000  # keeps the offset far inside bigint
EVENTS_INTERVAL = 2.0  # seconds (API-001.D3)
EVENTS_KEEPALIVE_AFTER = 15.0  # seconds with no frame (API-001.D10)
# No caching, and no buffering in the ui-proxy (RUN-019.D1 also sets proxy_buffering off).
SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}

_DETAILS = {503: DB_UNAVAILABLE, 500: INTERNAL_ERROR}


def guarded[T](fn: Callable[[], T]) -> T:
    """Run `fn`; any failure becomes a fixed-text HTTP error, raised unchained.

    A database error is a 503, anything else a 500. Nothing is logged: SQLAlchemy errors can
    quote SQL parameters (a category name) and pydantic errors quote `input_value`. The
    HTTPException is raised after the `try` statement, so `__cause__` and `__context__` are
    both None (m3 checklist item 5).
    """
    code = 0
    try:
        return fn()
    except SQLAlchemyError:
        code = 503
    except Exception:
        code = 500
    raise HTTPException(status_code=code, detail=_DETAILS[code])


def _set_read_only(dbapi_conn: Any, _record: Any) -> None:
    """Every transaction on this connection is READ ONLY (API-001.1, R-API-2 is read-only)."""
    cur = dbapi_conn.cursor()
    try:
        cur.execute("set session characteristics as transaction read only")
    finally:
        cur.close()
    dbapi_conn.commit()


def make_read_only(engine: Engine) -> Engine:
    """Add the read-only connect listener to `engine` (once), and return it.

    This mutates the engine it is given, a caller-supplied one included: every connection
    that engine opens from then on is read-only, for every user of the engine, not only the
    app. Connections it opened before the listener was added are not changed.
    """
    if not event.contains(engine, "connect", _set_read_only):
        event.listen(engine, "connect", _set_read_only)
    return engine


def read_only_engine(dsn: str) -> Engine:
    """A NullPool engine whose sessions are read-only; SQL parameters stay out of errors.

    A malformed DSN raises fixed text, unchained: SQLAlchemy's own error quotes the DSN,
    password included.
    """
    failed = False
    try:
        engine = create_engine(to_sqlalchemy_url(dsn), poolclass=NullPool, hide_parameters=True)
    except Exception:
        failed = True
    if failed:
        raise ValueError(BAD_DSN)
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
            # One snapshot, so a page's rows and its total agree (round 1, optional).
            conn.execute(text("set transaction isolation level repeatable read, read only"))
            yield conn

    def _read[T](fn: Callable[[Connection], T]) -> T:
        with _connection() as conn:
            return fn(conn)

    def _json(view: BaseModel) -> JSONResponse:
        return JSONResponse(content=view.model_dump(mode="json"))

    # The views are built and serialized inside `guarded`, so no exception reaches
    # Starlette, whose error middleware would log the traceback.
    @app.get("/api/files", response_class=JSONResponse)
    def api_files(
        status: FileStatus | None = None,
        format: str | None = None,
        topic: str | None = None,
        needs_review: bool | None = None,
        page: Annotated[int, Query(ge=1, le=MAX_PAGE)] = 1,
    ) -> JSONResponse:
        def build() -> JSONResponse:
            filters = FileFilters(
                status=status, format=format, topic=topic, needs_review=needs_review
            )
            page_view: FilePage = _read(lambda conn: build_file_page(conn, filters, page))
            return _json(page_view)

        return guarded(build)

    def _status_view() -> StatusView:
        view: StatusView = _read(build_status)  # the connection is closed here
        return with_loaded_models(view, probe)  # then Ollama (round 1, item 4)

    @app.get("/api/status", response_class=JSONResponse)
    def api_status() -> JSONResponse:
        return guarded(lambda: _json(_status_view()))

    def _status_json() -> str:
        return guarded(lambda: _status_view().model_dump_json())

    @app.get("/api/events")
    async def api_events(request: Request) -> StreamingResponse:
        """API-001.D3: the status JSON on change, every `events_interval` seconds."""
        stream = status_events(
            _status_json,
            interval=app.state.events_interval,
            keepalive_after=app.state.events_keepalive_after,
            sleep=app.state.events_sleep,
            is_disconnected=request.is_disconnected,
            internal_error=INTERNAL_ERROR,
            max_ticks=app.state.events_max_ticks,
        )
        return StreamingResponse(stream, media_type="text/event-stream", headers=SSE_HEADERS)

    app.state.engine = engine
    app.state.probe = probe
    # API-001.D3, D10. Tests swap the sleep and bound the ticks; production never does.
    app.state.events_interval = EVENTS_INTERVAL
    app.state.events_keepalive_after = EVENTS_KEEPALIVE_AFTER
    app.state.events_sleep = anyio.sleep
    app.state.events_max_ticks = None
    return app
