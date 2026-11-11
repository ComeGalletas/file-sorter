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
  5. every adult row's `img.thumb` carries `data-blur="1"` in the served HTML (API-001.D8);
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
from dataclasses import dataclass, field
from enum import StrEnum
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "docker-compose.yml"

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
    if served is None:
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


def check_counts(ledger: Sequence[LedgerRow], status: Mapping[str, Any] | None) -> Finding:
    """`status` is `/api/status`'s JSON. Zero entries are ignored on both sides."""
    if status is None:
        return _unavailable(2)
    try:
        served_status = _nonzero({str(k): int(n) for k, n in status["counts_by_status"].items()})
        served_grid: Counter[tuple[Any, Any, Any]] = Counter()
        for cell in status["grid"]:
            served_grid[(cell["topic"], cell["format"], cell["branch"])] += int(cell["count"])
    except (KeyError, TypeError, ValueError, AttributeError):
        malformed = True
    else:
        malformed = False
    if malformed:  # outside the except block: nothing chained (m3 privacy item 5)
        return Finding(2, False, ((NO_HASH, Code.UNREADABLE),))
    ledger_status = _nonzero(Counter(row.status for row in ledger))
    ledger_grid = _nonzero(Counter((row.topic, row.format, row.branch) for row in ledger))
    issues: list[tuple[str, Code]] = []
    for name in sorted(ledger_status.keys() | served_status.keys()):
        if ledger_status.get(name, 0) != served_status.get(name, 0):
            # The status is a fixed enum value, but it is kept out of the code: codes are fixed.
            issues.append((NO_HASH, Code.STATUS_MISMATCH))
    if _nonzero(served_grid) != ledger_grid:
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
    if queue is None:
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
    """The raw stems to look for, after TST-015.D4's skips."""
    sanitized = (row.original_sanitized or "").casefold()
    stems = []
    for path in (row.source_path, *row.duplicate_paths):
        stem = PurePosixPath(path).stem if path else ""
        if len(stem) >= MIN_RAW_STEM and stem.casefold() != sanitized:
            stems.append(stem)
    return stems


def check_no_leak(ledger: Sequence[LedgerRow], bodies: Mapping[str, str | None]) -> Finding:
    """`bodies` maps a fixed source label to everything that source served (headers included),
    or to None when it isn't available. Every row must first be proved served."""
    texts = [body.casefold() for body in bodies.values() if body]
    issues: list[tuple[str, Code]] = []
    if not bodies or any(body is None for body in bodies.values()):
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
# Lands with TST-015.1.3: it uses `classifier.api.views.is_adult` (API-001.D8 as corrected), never
# a retyped branch literal. Until then the criterion has no finding, so it fails.


# --- 6. report ----------------------------------------------------------------------------

_REF_ATTRS = frozenset(
    {"src", "href", "srcset", "action", "formaction", "poster", "data", "xlink:href", "ping"}
)
_CSS_REF = re.compile(r"url\(\s*['\"]?(?!#)|@import", re.IGNORECASE)


def check_report(report: str | None) -> Finding:
    """No `http(s)://`, no reference that leaves the page (anything but `#...`), no CSS
    `url()` or `@import`, and no thumbnail (`<img>`, a `/thumbs/` path, `data:image`)."""
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
        for name, value in attrs.items():
            if name in _REF_ATTRS and not value.strip().startswith("#"):
                issues.append((NO_HASH, Code.EXTERNAL_REF))
    return _finding(6, issues)


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


def main(argv: Sequence[str] | None = None) -> int:
    print("gate 4 FAIL: the runner is not wired yet (TST-015.1.3)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
