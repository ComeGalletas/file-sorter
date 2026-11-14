"""API-001.4: the UI routes, all GET (R-API-5, R-API-8).

`create_app` includes `ui_router(...)`, handing it its read-only connection runner, its
fixed-text guard and its status builder, so this module never imports `classifier.api.app`.

- `/` is the static dashboard and `/ui/app.js` its only script, plain JavaScript served
  from the package, with no third-party library and no CDN (m4 item 14, DOC-016.D1).
- The fragments: `/ui/banner`, `/ui/grid`, `/ui/latest`, `/ui/errors?page=N` (API-001.D2)
  and `/ui/review?page=N` (API-001.D9). A bad `page` gets the app's fixed 422.
- Every response carries a CSP that allows only the page's own origin and no inline script
  (API-001.D13), plus no-referrer and nosniff.
"""

from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import Connection

from classifier.api.views import StatusView, build_status
from classifier.ui import fragments, queries

UI_DIR = Path(__file__).resolve().parent
INDEX = UI_DIR / "index.html"
APP_JS = UI_DIR / "app.js"
NOT_FOUND = "not found"  # the app's handler gives every 404 this body (API-001.D12)
MAX_PAGE = 1_000_000  # the same bound as classifier.api.app.MAX_PAGE (pinned by a test)

# API-001.D13: own origin only, no inline script; inline style is the page's one stylesheet.
CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
UI_HEADERS = {
    "Content-Security-Policy": CSP,
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
}
JS_MEDIA_TYPE = "text/javascript; charset=utf-8"

Page = Annotated[int, Query(ge=1, le=MAX_PAGE)]
Read = Callable[[Callable[[Connection], Any]], Any]
Guard = Callable[[Callable[[], Any]], Any]


def _html(body: str) -> HTMLResponse:
    return HTMLResponse(content=body, headers=UI_HEADERS)


def _static(path: Path, media_type: str) -> Response:
    """A packaged file, or the fixed 404 when it isn't there."""
    if not path.is_file():
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return Response(content=path.read_bytes(), media_type=media_type, headers=UI_HEADERS)


def ui_router(*, read: Read, guard: Guard, status: Callable[[], StatusView]) -> APIRouter:
    router = APIRouter()

    @router.get("/", response_class=HTMLResponse)
    def index() -> Response:
        return _static(INDEX, "text/html; charset=utf-8")

    @router.get("/ui/app.js")
    def app_js() -> Response:
        return _static(APP_JS, JS_MEDIA_TYPE)

    @router.get("/ui/banner", response_class=HTMLResponse)
    def banner() -> HTMLResponse:
        return guard(lambda: _html(fragments.banner(status())))

    @router.get("/ui/grid", response_class=HTMLResponse)
    def grid() -> HTMLResponse:
        return guard(lambda: _html(fragments.grid(read(build_status))))

    @router.get("/ui/latest", response_class=HTMLResponse)
    def latest() -> HTMLResponse:
        return guard(lambda: _html(fragments.latest(read(queries.latest_rows))))

    @router.get("/ui/errors", response_class=HTMLResponse)
    def errors(page: Page = 1) -> HTMLResponse:
        def build() -> HTMLResponse:
            return _html(fragments.errors(read(lambda c: queries.error_rows(c, page)), page))

        return guard(build)

    @router.get("/ui/review", response_class=HTMLResponse)
    def review(page: Page = 1) -> HTMLResponse:
        def build() -> HTMLResponse:
            return _html(fragments.review(read(lambda c: queries.review_rows(c, page)), page))

        return guard(build)

    return router
