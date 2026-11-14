"""Milestone 4 gate: Status UI, read-only (DESIGN.md §11; TST-015).

Criterion: A dry run of the whole real folder is reviewable end to end without a terminal.

The gate reads the app database's ledger read-only (`APP_DB_DSN`, as TST-013 does) and runs
`create_app` in-process, then checks, against that ledger:
  1. every row is reachable through `/api/files`, paging to the end (API-001.D5);
  2. `/api/status`'s counts equal the ledger's, per status and per topic x format x branch;
  3. every unsorted or `needs_review` row is in the review queue, `GET /ui/review` (API-001.D9);
  4. no response, fragment, SSE event or report carries any row's `source_path`, any
     `duplicate_paths` entry, or the raw file name taken from them. Compared in memory only,
     and only after each row is proved served (its short hash appears in some body);
  5. every adult `img.thumb` on any served fragment (latest, review, errors) carries
     `data-blur="1"` (API-001.D8), and `/api/files`' `blurred` flag equals `is_adult` on
     every row (API-001.3; TST-015.D7: the dashboard shows only the newest rows);
  6. the report is self-contained: no external reference and no thumbnail (m4 answer 3);
  7. `docker-compose.yml` publishes only `127.0.0.1` ports (R-RUN-1).

QA owns this file. The public output is one verdict per criterion and the overall verdict, with
no counts or percents (TST-015.D1). `--detail` (box console only) adds, for failing criteria,
lines of a short hash and a fixed code, never a path, a raw name, a sanitized name or a category
name (TST-015.D3). A source that isn't available yet fails with `NOT_AVAILABLE`; it never passes.
Every error is fixed text; ledger values that hold a path or a name are repr=False.
"""

import html
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "docker-compose.yml"
CONFIG = REPO / "config.yaml"

# `python scripts/gate_4.py` puts scripts/ on sys.path; the lazy `classifier` imports need the repo.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

UNSORTED_FORMAT = "unsorted"  # the format fallback (P-6)
MIN_RAW_STEM = 4  # TST-015.D4: shorter raw stems are not checked (they match HTML noise)
_SHORT_HASH = re.compile(r"[0-9a-f]{8}")
NO_HASH = "-"


class Code(StrEnum):
    """The only things `--detail` prints besides short hashes (TST-015.D3)."""

    MISSING = "MISSING"
    EXTRA = "EXTRA"
    DUPLICATE = "DUPLICATE"
    STATUS_MISMATCH = "STATUS_MISMATCH"
    GRID_MISMATCH = "GRID_MISMATCH"
    NOT_IN_QUEUE = "NOT_IN_QUEUE"
    NOT_SERVED = "NOT_SERVED"
    LEAK_PATH = "LEAK_PATH"
    LEAK_DUP = "LEAK_DUP"
    LEAK_NAME = "LEAK_NAME"
    NOT_BLURRED = "NOT_BLURRED"
    BLUR_FLAG = "BLUR_FLAG"
    NO_ADULT_THUMB = "NO_ADULT_THUMB"
    EXTERNAL_REF = "EXTERNAL_REF"
    THUMB_IN_REPORT = "THUMB_IN_REPORT"
    PORT_NOT_LOCAL = "PORT_NOT_LOCAL"
    HOST_NETWORK = "HOST_NETWORK"
    UNREADABLE = "UNREADABLE"
    NOT_AVAILABLE = "NOT_AVAILABLE"


CRITERIA = {
    1: "every row reachable through /api/files",
    2: "status counts equal the ledger",
    3: "review queue complete",
    4: "no path or raw name served",
    5: "adult thumbnails blurred by default",
    6: "report self-contained",
    7: "compose publishes 127.0.0.1 only",
}


@dataclass(frozen=True)
class LedgerRow:
    """One `files` row, as the gate reads it. Paths and names never reach a repr."""

    source_hash: str
    short_hash: str
    status: str
    branch: str | None
    needs_review: bool
    format: str | None = field(repr=False)  # a category name
    topic: str | None = field(repr=False)  # a category name
    source_path: str = field(repr=False)
    duplicate_paths: tuple[str, ...] = field(repr=False)
    original_sanitized: str | None = field(repr=False)


@dataclass(frozen=True)
class Finding:
    """One criterion's result: `issues` holds (short hash or "-", code) pairs only."""

    criterion: int
    passed: bool
    issues: tuple[tuple[str, Code], ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class Verdict:
    passed: bool
    lines: tuple[str, ...]
    detail: tuple[str, ...] = field(default=(), repr=False)


def _short(value: str) -> str:
    """A printable short hash, or a fixed placeholder: nothing else ever reaches `--detail`."""
    head = value[:8]
    return head if _SHORT_HASH.fullmatch(head) else "????????"


def _printable(short: str) -> str:
    return NO_HASH if short == NO_HASH else _short(short)


def _finding(criterion: int, issues: Iterable[tuple[str, Code]]) -> Finding:
    unique = tuple(sorted(set(issues)))
    return Finding(criterion, not unique, unique)


def _unavailable(criterion: int) -> Finding:
    return Finding(criterion, False, ((NO_HASH, Code.NOT_AVAILABLE),))


# --- 1. reachable -------------------------------------------------------------------------


def check_reachable(ledger: Sequence[LedgerRow], served: Sequence[str] | None) -> Finding:
    """`served` is every `source_hash` from `/api/files`, all pages in order; None = no route."""
    if served is None or not ledger:  # a whole-folder run is never empty
        return _unavailable(1)
    expected = {row.source_hash for row in ledger}
    seen = Counter(served)
    issues = [(_short(h), Code.MISSING) for h in expected - seen.keys()]
    issues += [(_short(h), Code.EXTRA) for h in seen.keys() - expected]
    issues += [(_short(h), Code.DUPLICATE) for h, n in seen.items() if n > 1]
    return _finding(1, issues)


# --- 2. counts ----------------------------------------------------------------------------


def _nonzero(counts: Mapping[Any, int]) -> dict[Any, int]:
    return {k: n for k, n in counts.items() if n}


def _count(value: Any) -> bool:
    return type(value) is int and value >= 0  # not a bool, a float or a numeric string


def _served_counts(
    status: Mapping[str, Any],
) -> tuple[dict[str, int], dict[tuple[Any, ...], int]] | None:
    """`/api/status`'s counts per status and per (topic, format, branch), or None when the
    shape isn't exactly the read model's. Checked by type, so nothing raises."""
    by_status = status.get("counts_by_status") if isinstance(status, Mapping) else None
    grid = status.get("grid") if isinstance(status, Mapping) else None
    if not isinstance(by_status, Mapping) or not isinstance(grid, list):
        return None
    if not all(isinstance(k, str) and _count(n) for k, n in by_status.items()):
        return None
    from classifier.api.views import is_adult

    cells: Counter[tuple[Any, ...]] = Counter()
    for cell in grid:
        if not isinstance(cell, Mapping) or not _count(cell.get("count")):
            return None
        key = (cell.get("topic"), cell.get("format"), cell.get("branch"))
        if not all(part is None or isinstance(part, str) for part in key):
            return None
        if type(cell.get("adult")) is not bool:
            return None
        # A wrong safe-vs-adult flag can't match any ledger cell: the flag is part of the key.
        cells[(*key, cell["adult"] is is_adult(key[2]))] += cell["count"]
    return _nonzero(dict(by_status)), _nonzero(cells)


def check_counts(ledger: Sequence[LedgerRow], status: Mapping[str, Any] | None) -> Finding:
    """`status` is `/api/status`'s JSON. Zero entries are ignored on both sides."""
    if status is None:
        return _unavailable(2)
    served = _served_counts(status)
    if served is None:
        return Finding(2, False, ((NO_HASH, Code.UNREADABLE),))
    served_status, served_grid = served
    ledger_status = _nonzero(Counter(row.status for row in ledger))
    ledger_grid = _nonzero(Counter((row.topic, row.format, row.branch, True) for row in ledger))
    issues: list[tuple[str, Code]] = []
    for name in sorted(ledger_status.keys() | served_status.keys()):
        if ledger_status.get(name, 0) != served_status.get(name, 0):
            # The status is a fixed enum value, but it is kept out of the code: codes are fixed.
            issues.append((NO_HASH, Code.STATUS_MISMATCH))
    if served_grid != ledger_grid:
        issues.append((NO_HASH, Code.GRID_MISMATCH))  # never the cell: it holds category names
    return _finding(2, issues)


# --- HTML -------------------------------------------------------------------------------


class _Tags(HTMLParser):
    """Every start tag with its attributes; nothing else is kept."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[tuple[str, dict[str, str]]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append((tag, {k: v or "" for k, v in attrs}))


def _tags(text: str) -> list[tuple[str, dict[str, str]]]:
    parser = _Tags()
    parser.feed(text)
    parser.close()
    return parser.tags


# --- 3. review queue ----------------------------------------------------------------------


def queued(row: LedgerRow) -> bool:
    """API-001.D9: `needs_review`, or the `unsorted` format fallback."""
    return row.needs_review or row.format == UNSORTED_FORMAT


def queue_entries(pages: Iterable[str]) -> list[str]:
    """The `data-source-hash` of every `<tr data-hash>` in the `/ui/review` fragments."""
    return [
        attrs.get("data-source-hash", "")
        for page in pages
        for tag, attrs in _tags(page)
        if tag == "tr" and "data-hash" in attrs
    ]


def check_review_queue(ledger: Sequence[LedgerRow], queue: Sequence[str] | None) -> Finding:
    """`queue` is every `data-source-hash` from `/ui/review`, all pages; None = no route."""
    if queue is None or not ledger:
        return _unavailable(3)
    expected = {row.source_hash for row in ledger if queued(row)}
    seen = Counter(queue)
    issues = [(_short(h), Code.NOT_IN_QUEUE) for h in expected - seen.keys()]
    issues += [(_short(h), Code.EXTRA) for h in seen.keys() - expected]
    issues += [(_short(h), Code.DUPLICATE) for h, n in seen.items() if n > 1]
    return _finding(3, issues)


# --- 4. no leak ---------------------------------------------------------------------------


def _forms(secret: str) -> set[str]:
    """The ways a value can appear in a body: raw, HTML-escaped, JSON-escaped, URL-quoted."""
    forms = {
        secret,
        html.escape(secret, quote=True),
        html.escape(secret, quote=False),
        json.dumps(secret)[1:-1],
        json.dumps(secret, ensure_ascii=False)[1:-1],
        quote(secret, safe="/", errors="surrogatepass"),
        quote(secret, safe="", errors="surrogatepass"),
    }
    return {form.casefold() for form in forms if form}


def raw_stems(row: LedgerRow) -> list[str]:
    """The raw stems to look for, after TST-015.D4's skips: under 4 characters, or equal to
    `original_sanitized` (casefolded) on its own or with its extension."""
    sanitized = (row.original_sanitized or "").casefold()
    stems = []
    for path in (row.source_path, *row.duplicate_paths):
        raw = PurePosixPath(path) if path else PurePosixPath()
        same = sanitized in (raw.stem.casefold(), raw.name.casefold())
        if len(raw.stem) >= MIN_RAW_STEM and not same:
            stems.append(raw.stem)
    return stems


def check_no_leak(ledger: Sequence[LedgerRow], bodies: Mapping[str, str | None]) -> Finding:
    """`bodies` maps a fixed source label to everything that source served (headers included),
    or to None when it isn't available. Every row must first be proved served."""
    texts = [body.casefold() for body in bodies.values() if body]
    issues: list[tuple[str, Code]] = []
    if not ledger or not bodies or any(body is None for body in bodies.values()):
        issues.append((NO_HASH, Code.NOT_AVAILABLE))

    def found(secret: str) -> bool:
        forms = _forms(secret)
        return any(form in text for text in texts for form in forms)

    for row in ledger:
        short = _short(row.short_hash)
        if not any(row.short_hash.casefold() in text for text in texts):
            issues.append((short, Code.NOT_SERVED))  # absence would prove nothing
        if row.source_path and found(row.source_path):
            issues.append((short, Code.LEAK_PATH))
        if any(path and found(path) for path in row.duplicate_paths):
            issues.append((short, Code.LEAK_DUP))
        if any(found(stem) for stem in raw_stems(row)):
            issues.append((short, Code.LEAK_NAME))
    return _finding(4, issues)


# --- 5. blur ------------------------------------------------------------------------------


def check_blur(
    ledger: Sequence[LedgerRow],
    pages: Sequence[str] | None,
    flags: Mapping[str, Any] | None = None,
) -> Finding:
    """API-001.D8: every `img.thumb` of an adult row (`is_adult`, never a retyped branch) has
    `data-blur="1"` in the served HTML, matched by `data-hash`. At least one adult thumbnail
    must be seen when the ledger has adult rows, or the check would prove nothing.

    `flags` maps each `source_hash` to the `blurred` field `/api/files` served (API-001.3).
    Every ledger row's flag must be a bool equal to `is_adult` of its branch; this part runs
    even while the HTML isn't available."""
    from classifier.api.views import is_adult

    if not ledger:
        return _unavailable(5)
    issues: list[tuple[str, Code]] = []
    if flags is not None:
        for row in ledger:
            flag = flags.get(row.source_hash)
            if type(flag) is not bool or flag is not is_adult(row.branch):
                issues.append((_short(row.short_hash), Code.BLUR_FLAG))
    if pages is None:
        issues.append((NO_HASH, Code.NOT_AVAILABLE))
        return _finding(5, issues)
    adult = {row.short_hash for row in ledger if is_adult(row.branch)}
    seen_adult = False
    for page in pages:
        for tag, attrs in _tags(page):
            if tag != "img" or "thumb" not in attrs.get("class", "").split():
                continue
            short = attrs.get("data-hash", "")
            if short not in adult:
                continue
            seen_adult = True
            if attrs.get("data-blur") != "1":
                issues.append((_short(short), Code.NOT_BLURRED))
    if adult and not seen_adult:
        issues.append((NO_HASH, Code.NO_ADULT_THUMB))
    return _finding(5, issues)


# --- 6. report ----------------------------------------------------------------------------

_REF_ATTRS = frozenset(
    {"src", "href", "srcset", "action", "formaction", "poster", "data", "xlink:href", "ping"}
)
_CSS_REF = re.compile(r"url\(\s*['\"]?(?!#)|@import", re.IGNORECASE)


def check_report(report: str | None) -> Finding:
    """No `http(s)://`, no reference that leaves the page (anything but `#...`), no CSS
    `url()` or `@import`, no `<meta http-equiv="refresh">`, and no thumbnail (`<img>`, a
    `/thumbs/` path, `data:image`)."""
    if report is None:
        return _unavailable(6)
    lowered = report.casefold()
    issues: list[tuple[str, Code]] = []
    if "http://" in lowered or "https://" in lowered or _CSS_REF.search(report):
        issues.append((NO_HASH, Code.EXTERNAL_REF))
    if "/thumbs/" in lowered or "data:image" in lowered:
        issues.append((NO_HASH, Code.THUMB_IN_REPORT))
    for tag, attrs in _tags(report):
        if tag == "img":
            issues.append((NO_HASH, Code.THUMB_IN_REPORT))
        if tag == "meta" and attrs.get("http-equiv", "").strip().casefold() == "refresh":
            issues.append((NO_HASH, Code.EXTERNAL_REF))  # any refresh navigates the page
        for name, value in attrs.items():
            if name in _REF_ATTRS and not value.strip().startswith("#"):
                issues.append((NO_HASH, Code.EXTERNAL_REF))
    return _finding(6, issues)


# --- 7. compose ---------------------------------------------------------------------------

LOCALHOST = "127.0.0.1"


def _local_port(entry: Any) -> bool:
    """Short syntax must be `127.0.0.1:<host>:<container>[/proto]`; long syntax must set
    `host_ip: 127.0.0.1`. Anything else (a bare container port, an interpolated host, an
    IPv6 or wildcard address) publishes beyond localhost or can't be proved not to."""
    if isinstance(entry, str):
        parts = entry.split(":")
        return len(parts) == 3 and parts[0] == LOCALHOST and all(parts[1:])
    if isinstance(entry, dict):
        return entry.get("host_ip") == LOCALHOST
    return False


def check_compose(text: str | None) -> Finding:
    """Every service's `ports` binds 127.0.0.1, and no service uses the host network (R-RUN-1)."""
    if text is None:
        return _unavailable(7)
    import yaml

    try:
        doc = yaml.safe_load(text)
    except yaml.YAMLError:
        doc = None
    services = doc.get("services") if isinstance(doc, dict) else None
    if not isinstance(services, dict):  # outside the except block: nothing chained
        return Finding(7, False, ((NO_HASH, Code.UNREADABLE),))
    issues: list[tuple[str, Code]] = []
    for service in services.values():
        if not isinstance(service, dict):
            issues.append((NO_HASH, Code.UNREADABLE))
            continue
        if service.get("network_mode") == "host":
            issues.append((NO_HASH, Code.HOST_NETWORK))
        ports = service.get("ports") or []
        if not isinstance(ports, list):
            issues.append((NO_HASH, Code.UNREADABLE))
            continue
        if not all(_local_port(entry) for entry in ports):
            issues.append((NO_HASH, Code.PORT_NOT_LOCAL))
    return _finding(7, issues)


def read_compose(path: Path = COMPOSE) -> str | None:
    """The compose file's text, or None when it can't be read (fixed handling, no path)."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


# --- the verdict --------------------------------------------------------------------------


def judge(findings: Sequence[Finding], detail: bool = False) -> Verdict:
    """One line per criterion and the overall line (TST-015.D1). A criterion with no finding
    fails. `detail` adds `<short hash> <code>` lines for the failing ones (TST-015.D3)."""
    by_criterion = {f.criterion: f for f in findings}
    lines = []
    extra = []
    for number, name in CRITERIA.items():
        finding = by_criterion.get(number) or _unavailable(number)
        lines.append(f"gate 4 criterion {number} ({name}): {'ok' if finding.passed else 'FAIL'}")
        if detail and not finding.passed:
            extra += [f"  {number} {_printable(h)} {Code(c).value}" for h, c in finding.issues]
    passed = all((by_criterion.get(n) or _unavailable(n)).passed for n in CRITERIA)
    lines.append(f"gate 4 {'PASS' if passed else 'FAIL'}")
    return Verdict(passed, tuple(lines), tuple(extra))


# --- the runner ---------------------------------------------------------------------------

NO_APP_DSN = (
    "APP_DB_DSN is not set: gate 4 reads the app database's dry run. Run it with "
    "`make gate-4` from the main checkout."
)
LEDGER_FAILED = "the app database's ledger could not be read"
# The UI's single-page routes (API-001.4), by their `bodies` source label; two more are paged.
UI_ROUTES = {
    "ui": "/",
    "app_js": "/ui/app.js",
    "banner": "/ui/banner",
    "grid": "/ui/grid",
    "latest": "/ui/latest",
}
ERRORS_ROUTE = "/ui/errors"  # API-001.D2, paged
REVIEW_ROUTE = "/ui/review"  # API-001.D9, paged
SOURCES = ("status", "files", "events", "report", *UI_ROUTES, "errors", "review")


class GateSetupError(Exception):
    """Fixed text only: never a DSN, a path or a driver message."""


class NoModels:
    """The gate's model probe: no Ollama call, so `/api/status` shows "n/a" (m4 answer 7)."""

    def loaded_models(self) -> None:
        return None


@dataclass(frozen=True)
class Served:
    """What the app served, per source; None = the source isn't available."""

    # Every content field is repr=False: the HTML and the report carry sanitized names, and the
    # status carries category names (round 2 on #230).
    files: list[str] | None = field(repr=False)
    status: dict[str, Any] | None = field(repr=False)
    queue: list[str] | None = field(repr=False)
    html: list[str] | None = field(repr=False)
    report: str | None = field(repr=False)
    bodies: dict[str, str | None] = field(repr=False)  # every body and header, for check 4
    blurred: dict[str, Any] | None = field(default=None, repr=False)  # source_hash -> flag


def load_config(dsn: str) -> Any:
    """config.yaml with the app database's DSN (never echoed)."""
    import yaml

    from classifier.config import Config

    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["db"] = {"dsn": dsn}
    return Config.model_validate(data)


def read_ledger(engine: Any) -> list[LedgerRow]:
    """Every `files` row, on the read-only engine. A failure is fixed text, unchained."""
    from sqlalchemy import select

    from classifier.db.models import File

    query = select(
        File.source_hash,
        File.short_hash,
        File.status,
        File.branch,
        File.needs_review,
        File.format,
        File.topic,
        File.source_path,
        File.duplicate_paths,
        File.original_sanitized,
    )
    rows: list[Any] | None = None
    try:
        with engine.connect() as conn:
            rows = list(conn.execute(query))
    except Exception:
        rows = None
    if rows is None:
        raise GateSetupError(LEDGER_FAILED)
    return [
        LedgerRow(
            source_hash=r.source_hash,
            short_hash=r.short_hash,
            status=getattr(r.status, "value", r.status),
            branch=r.branch,
            needs_review=bool(r.needs_review),
            format=r.format,
            topic=r.topic,
            source_path=r.source_path,
            duplicate_paths=tuple(r.duplicate_paths or ()),
            original_sanitized=r.original_sanitized,
        )
        for r in rows
    ]


def _text(response: Any) -> str:
    """A response's headers and body, as one string for check 4."""
    head = "\n".join(f"{k}: {v}" for k, v in response.headers.items())
    return f"{head}\n\n{response.text}"


def _max_pages(rows: int) -> int:
    from classifier.api.views import PER_PAGE

    return rows // PER_PAGE + 2  # one past the last full page, plus the empty end page


FilesRead = tuple[list[str] | None, str | None, dict[str, Any] | None]


def _files(client: Any, rows: int) -> FilesRead:
    """Every `source_hash` from `/api/files`, paging until an empty page (API-001.D5), the
    served text, and each row's `blurred` flag (API-001.3; absent reads as None)."""
    hashes: list[str] = []
    texts: list[str] = []
    flags: dict[str, Any] = {}
    for page in range(1, _max_pages(rows) + 1):
        response = client.get("/api/files", params={"page": page})
        if response.status_code != 200:
            return None, None, None
        texts.append(_text(response))
        body = response.json()
        page_rows = body.get("rows") if isinstance(body, dict) else None
        if not isinstance(page_rows, list):
            return None, None, None
        if not page_rows:
            return hashes, "\n".join(texts), flags
        for item in page_rows:
            value = item.get("source_hash") if isinstance(item, dict) else None
            if not isinstance(value, str):
                return None, None, None
            hashes.append(value)
            flags[value] = item.get("blurred")
    return None, None, None  # never reached an empty page: paging is broken


def _paged(client: Any, route: str, rows: int) -> tuple[list[str] | None, list[str] | None]:
    """Every `data-source-hash` of `route`'s `<tr data-hash>` rows, and each page's headers and
    body, paging until a page has no such row (API-001.D2, D9). A non-200 is None, None."""
    entries: list[str] = []
    pages: list[str] = []
    for page in range(1, _max_pages(rows) + 1):
        response = client.get(route, params={"page": page})
        if response.status_code != 200:
            return None, None  # a 404 on page 1: the UI isn't served
        pages.append(_text(response))
        found = queue_entries([response.text])
        if not found:
            return entries, pages
        entries += found
    return None, None  # never reached an empty page: paging is broken


STATUS_FRAME = "event: status\n"


def _events(client: Any) -> str | None:
    """One bounded `/api/events` read: the app is set to stop after one tick (see `run`), so
    the body ends. It must hold a status frame, or there was nothing to scan (API-001.D3)."""
    response = client.get("/api/events")
    if response.status_code != 200 or STATUS_FRAME not in response.text:
        return None
    return _text(response)


async def _no_sleep(_seconds: float) -> None:
    return None


def _page(client: Any, path: str) -> str | None:
    """One UI route's headers and body, or None when it isn't served."""
    response = client.get(path)
    return _text(response) if response.status_code == 200 else None


def _joined(pages: Sequence[str] | None) -> str | None:
    return None if pages is None else "\n".join(pages)


def collect(client: Any, rows: int) -> Served:
    """Everything the gate reads from the app, in-process; `serve` adds the report.

    The UI is read through its fixed routes (API-001.4: the page, its script and every
    fragment, the paged ones to the end), each into its own `bodies` source for check 4; any
    route not served makes its source None, so check 4 can't pass. Check 5's HTML is every
    fragment that carries thumbnails: `/ui/latest` (the newest rows, API-001.D1) and every
    review and errors page (`/` is a shell and holds none). A row that is neither recent nor
    queued has no thumbnail on any fragment; the `/api/files` `blurred` flag, checked on every
    row, covers it (TST-015.D7)."""
    status_response = client.get("/api/status")
    status = status_response.json() if status_response.status_code == 200 else None
    files, files_text, flags = _files(client, rows)
    queue, review_pages = _paged(client, REVIEW_ROUTE, rows)
    _, error_pages = _paged(client, ERRORS_ROUTE, rows)
    ui = {source: _page(client, route) for source, route in UI_ROUTES.items()}
    latest = ui["latest"]
    html_pages = (
        None
        if latest is None or review_pages is None or error_pages is None
        else [latest, *review_pages, *error_pages]
    )
    bodies: dict[str, str | None] = {
        "status": _text(status_response) if status is not None else None,
        "files": files_text,
        "events": _events(client),
        "report": None,  # filled by `serve`, from the ledger (API-001.5)
        **ui,
        "errors": _joined(error_pages),
        "review": _joined(review_pages),
    }
    return Served(
        files=files,
        status=status if isinstance(status, dict) else None,
        queue=queue,
        html=html_pages,
        report=None,  # filled by `serve`
        bodies=bodies,
        blurred=flags,
    )


def build_report(engine: Any) -> str | None:
    """`render_report` over the whole ledger, as `classifier report` builds it (API-001.5):
    the status and every row from API-001.1's views, in one read-only snapshot, with the
    gate's no-call model probe. Any failure reads as None (criterion 6 fails), no text kept."""
    from sqlalchemy import text

    from classifier.api.report import render_report
    from classifier.api.views import (
        FileFilters,
        build_status,
        file_row,
        rows_query,
        with_loaded_models,
    )

    report: str | None = None
    try:
        with engine.connect() as conn:
            conn.execute(text("set transaction isolation level repeatable read, read only"))
            status = with_loaded_models(build_status(conn), NoModels())
            rows = (file_row(m) for m in conn.execute(rows_query(FileFilters())).mappings())
            report = render_report(status, rows)
    except Exception:
        report = None
    return report


def evaluate(ledger: Sequence[LedgerRow], served: Served, compose: str | None) -> list[Finding]:
    return [
        check_reachable(ledger, served.files),
        check_counts(ledger, served.status),
        check_review_queue(ledger, served.queue),
        check_no_leak(ledger, served.bodies),
        check_blur(ledger, served.html, served.blurred),
        check_report(served.report),
        check_compose(compose),
    ]


def run(dsn: str, engine: Any = None) -> list[Finding]:
    """Read the ledger, serve it through `create_app`, and run the seven checks."""
    ledger, served = serve(dsn, engine)
    return evaluate(ledger, served, read_compose())


def serve(dsn: str, engine: Any = None) -> tuple[list[LedgerRow], Served]:
    """Read the ledger and serve it through `create_app`, in-process and read-only.
    `engine` is a test seam; by default the app's own read-only engine."""
    from fastapi.testclient import TestClient

    from classifier.api.app import create_app, make_read_only, read_only_engine

    engine = read_only_engine(dsn) if engine is None else make_read_only(engine)
    try:
        ledger = read_ledger(engine)
        app = create_app(load_config(dsn), engine=engine, ollama=NoModels())
        app.state.events_max_ticks = 1  # one status frame, then the stream ends (API-001.2 seam)
        app.state.events_sleep = _no_sleep
        with TestClient(app, raise_server_exceptions=False) as client:
            served = collect(client, len(ledger))
        report = build_report(engine)
        served = replace(served, report=report, bodies={**served.bodies, "report": report})
    finally:
        engine.dispose()
    return ledger, served


def main(argv: Sequence[str] | None = None, engine: Any = None) -> int:
    """`engine` is a test seam (tests/db/gate/test_gate_4_runner.py)."""
    import os

    args = sys.argv[1:] if argv is None else argv
    detail = "--detail" in args
    try:
        dsn = os.environ.get("APP_DB_DSN")
        if not dsn:
            raise GateSetupError(NO_APP_DSN)
        findings = run(dsn, engine)
    except GateSetupError as exc:  # fixed text
        print(f"gate 4 FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # the type only: a message can carry a value, a path or the DSN
        print(f"gate 4 FAIL: run errored ({type(exc).__name__})", file=sys.stderr)
        return 1
    verdict = judge(findings, detail)
    print("\n".join((*verdict.lines, *verdict.detail)))
    return 0 if verdict.passed else 1


if __name__ == "__main__":
    sys.exit(main())
