"""API-001.4: the server-rendered HTML fragments behind the dashboard and the review queue.

Pure functions over API-001.1's view models. Fixed markup plus `esc(value)` for every value
(API-001.D4), so nothing outside the allowlisted row fields can reach a page (m4 item 11).
Thumbnails follow API-001.D8 exactly; `data-blur` comes from `FileRow.blurred` (is_adult),
set server-side, so the initial HTML is always blurred for an adult row. Nothing here writes:
no form, no button, no write verb (R-API-8).
"""

from collections.abc import Sequence

from classifier.api.report import branch_label, grid_section, status_section
from classifier.api.views import PER_PAGE, FileRow, StatusView
from classifier.ui.html import esc

LATEST_HEADERS = ("", "hash", "sanitized name", "status", "branch", "format", "topic", "updated")
ERROR_HEADERS = ("hash", "status", "error", "updated")
REVIEW_HEADERS = (
    "",
    "hash",
    "sanitized name",
    "format",
    "topic",
    "NSFW level",
    "traces",
    "cross-check disagrees",
    "review reason",
)


def thumb(r: FileRow) -> str:
    """API-001.D8: the one thumbnail markup. No title, an empty alt."""
    blur = "1" if r.blurred else "0"
    return (
        f'<img class="thumb" src="/thumbs/{esc(r.source_hash)}" '
        f'data-hash="{esc(r.short_hash)}" data-blur="{blur}" alt="">'
    )


def header_row(headers: Sequence[str]) -> str:
    return "<tr>" + "".join(f"<th>{esc(h)}</th>" for h in headers) + "</tr>"


def _tds(values: Sequence[object]) -> str:
    return "".join(f"<td>{esc(v)}</td>" for v in values)


def _more(route: str, page: int, rows: Sequence[FileRow], colspan: int) -> str:
    """A full page ends with a row that loads the next page when scrolled into view."""
    if len(rows) < PER_PAGE:
        return ""
    return (
        f'<tr class="more" hx-get="{route}?page={page + 1}" hx-trigger="revealed" '
        f'hx-swap="outerHTML"><td colspan="{colspan}">more</td></tr>\n'
    )


def banner(status: StatusView) -> str:
    return status_section(status)


def grid(status: StatusView) -> str:
    return grid_section(status.grid)


def latest(rows: Sequence[FileRow]) -> str:
    """API-001.D1: the latest 20 rows, labelled "latest" (it becomes "filed" in M7)."""
    out = ["<table>", header_row(LATEST_HEADERS), "\n"]
    for r in rows:
        values = (
            r.short_hash,
            r.sanitized_name,
            r.status,
            branch_label(r.branch),
            r.format,
            r.topic,
            r.updated_at.isoformat(),
        )
        out.append(f'<tr data-hash="{esc(r.short_hash)}"><td>{thumb(r)}</td>{_tds(values)}</tr>\n')
    out.append("</table>\n")
    return "".join(out)


def errors(rows: Sequence[FileRow], page: int) -> str:
    """API-001.D2: the short hash, status and fixed error code; no retry (a write, M8)."""
    out = []
    for r in rows:
        values = (r.short_hash, r.status, r.error, r.updated_at.isoformat())
        out.append(f'<tr data-hash="{esc(r.short_hash)}">{_tds(values)}</tr>\n')
    out.append(_more("/ui/errors", page, rows, len(ERROR_HEADERS)))
    return "".join(out)


def review(rows: Sequence[FileRow], page: int) -> str:
    """API-001.D9: one `<tr data-hash data-source-hash>` per queued row; empty past the end."""
    out = []
    for r in rows:
        values = (
            r.short_hash,
            r.sanitized_name,
            r.format,
            r.topic,
            r.nsfw_level,
            r.nsfw_traces,
            r.cross_check_disagrees,
            r.review_reason,
        )
        out.append(
            f'<tr data-hash="{esc(r.short_hash)}" data-source-hash="{esc(r.source_hash)}">'
            f"<td>{thumb(r)}</td>{_tds(values)}</tr>\n"
        )
    out.append(_more("/ui/review", page, rows, len(REVIEW_HEADERS)))
    return "".join(out)
