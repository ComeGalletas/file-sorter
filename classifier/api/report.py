"""API-001.5: the self-contained HTML report (R-API-7).

`render_report` is pure: no I/O, no database, no clock, no logging. CLI-008.1 writes the file
(API-001.D6). The page is built from API-001.1's view models only, so it can never carry
`source_path`, `duplicate_paths` or a raw name (m4 privacy item 11), and every value goes
through the one escaping helper (API-001.D4, item 12).

It is self-contained: inline CSS, no script, no thumbnails (m4 answer 3), no link and no URL
(item 14). Its Content-Security-Policy refuses every load, so even a reference that slipped in
couldn't reach anything.

The grid is split three ways (lead, #213): adult cells (`GridCell.adult`, from `is_adult`,
API-001.D8), not classified (a null branch), and safe (every other branch).
"""

from collections.abc import Iterable

from classifier.api.views import FileRow, GridCell, RunView, StatusView, is_adult
from classifier.ui.html import esc

NOT_CLASSIFIED = "not classified"

_CSS = """
body{font:14px/1.4 system-ui,sans-serif;margin:16px;color:#1b1b1b;background:#fff}
h1{font-size:20px}h2{font-size:16px;margin-top:24px}
table{border-collapse:collapse;margin:8px 0}
th,td{border:1px solid #ccc;padding:2px 6px;text-align:left;vertical-align:top}
th{background:#f2f2f2}td.n{text-align:right}
tr.adult td{background:#fbeaea}
@media (prefers-color-scheme:dark){
body{color:#e6e6e6;background:#161616}th{background:#262626}th,td{border-color:#444}
tr.adult td{background:#3a1f1f}}
"""

_HEAD = (
    "<!doctype html>\n"
    '<html lang="en"><head><meta charset="utf-8">'
    '<meta http-equiv="Content-Security-Policy" '
    "content=\"default-src 'none'; style-src 'unsafe-inline'\">"
    '<meta name="referrer" content="no-referrer">'
    '<meta name="viewport" content="width=device-width, initial-scale=1">'
    "<title>file-sorter report</title>"
    f"<style>{_CSS}</style></head><body>\n<h1>file-sorter report</h1>\n"
)

_ROW_HEADERS = (
    "hash",
    "sanitized name",
    "status",
    "branch",
    "format",
    "topic",
    "NSFW level",
    "traces",
    "cross-check disagrees",
    "blurred",
    "needs review",
    "review reason",
    "error",
    "updated",
)


def branch_label(branch: str | None) -> str:
    """adult / not classified / safe, decided by `is_adult` (API-001.D8), never a literal."""
    if is_adult(branch):
        return "adult"
    if branch is None:
        return NOT_CLASSIFIED
    return "safe"


def _kv_table(pairs: Iterable[tuple[str, object]]) -> str:
    body = "".join(f"<tr><th>{esc(k)}</th><td>{esc(v)}</td></tr>" for k, v in pairs)
    return f"<table>{body}</table>\n"


def _run_section(run: RunView | None, imgs_per_min: float | None) -> str:
    if run is None:
        return "<h2>Run</h2>\n<p>no run</p>\n"
    rate = None if imgs_per_min is None else f"{imgs_per_min:.1f}"
    out = "<h2>Run</h2>\n" + _kv_table(
        [
            ("kind", run.kind),
            ("state", run.state),
            ("started", run.started_at.isoformat()),
            ("finished", None if run.finished_at is None else run.finished_at.isoformat()),
            ("error", run.error),
            ("imgs/min", rate),
        ]
    )
    if run.counts:
        cells = "".join(
            f"<tr><td>{esc(node)}</td><td>{esc(field)}</td><td class=n>{esc(n)}</td></tr>"
            for node, fields in sorted(run.counts.items())
            for field, n in sorted(fields.items())
        )
        out += f"<table><tr><th>node</th><th>field</th><th>count</th></tr>{cells}</table>\n"
    return out


def _status_section(status: StatusView) -> str:
    out = _run_section(status.run, status.imgs_per_min)
    out += "<h2>Files by status</h2>\n" + _kv_table(sorted(status.counts_by_status.items()))
    out += "<h2>Loaded models</h2>\n"
    if isinstance(status.loaded_models, str):
        out += f"<p>{esc(status.loaded_models)}</p>\n"
    elif not status.loaded_models:
        out += "<p>none</p>\n"
    else:
        out += _kv_table((m.name, f"{m.size_vram} bytes") for m in status.loaded_models)
    out += "<h2>Last error</h2>\n"
    e = status.last_error
    if e is None:
        out += "<p>none</p>\n"
    else:
        out += _kv_table(
            [
                ("hash", e.short_hash),
                ("status", e.status),
                ("error", e.error),
                ("updated", e.updated_at.isoformat()),
            ]
        )
    return out


def _sort_key(value: str | None) -> tuple[bool, str]:
    return (value is None, value or "")


def _grid_table(title: str, cells: list[GridCell]) -> str:
    out = f"<h2>{esc(title)}</h2>\n"
    if not cells:
        return out + "<p>none</p>\n"
    formats = sorted({c.format for c in cells}, key=_sort_key)
    topics = sorted({c.topic for c in cells}, key=_sort_key)
    counts: dict[tuple[str | None, str | None], int] = {}
    for c in cells:
        counts[(c.topic, c.format)] = counts.get((c.topic, c.format), 0) + c.count
    head = "<tr><th>topic ↓ / format →</th>"
    head += "".join(f"<th>{esc(f)}</th>" for f in formats) + "</tr>"
    body = ""
    for t in topics:
        row = "".join(f"<td class=n>{esc(counts.get((t, f), 0))}</td>" for f in formats)
        body += f"<tr><th>{esc(t)}</th>{row}</tr>"
    return out + f"<table>{head}{body}</table>\n"


def _grid_section(grid: list[GridCell]) -> str:
    adult = [c for c in grid if c.adult]
    unclassified = [c for c in grid if not c.adult and c.branch is None]
    safe = [c for c in grid if not c.adult and c.branch is not None]
    return (
        _grid_table("Topic × format: safe", safe)
        + _grid_table("Topic × format: adult", adult)
        + _grid_table(f"Topic × format: {NOT_CLASSIFIED}", unclassified)
    )


def _file_row(r: FileRow) -> str:
    cls = ' class="adult"' if is_adult(r.branch) else ""
    cells = (
        r.short_hash,
        r.sanitized_name,
        r.status,
        branch_label(r.branch),
        r.format,
        r.topic,
        r.nsfw_level,
        r.nsfw_traces,
        r.cross_check_disagrees,
        r.blurred,  # API-001.3; the report embeds no thumbnail, it only shows the flag
        r.needs_review,
        r.review_reason,
        r.error,
        r.updated_at.isoformat(),
    )
    tds = "".join(f"<td>{esc(v)}</td>" for v in cells)
    return f'<tr data-hash="{esc(r.short_hash)}"{cls}>{tds}</tr>\n'


def render_report(status: StatusView, files: Iterable[FileRow]) -> str:
    """The whole report as one HTML string. `files` is consumed once, in its own order."""
    parts = [_HEAD, _status_section(status), _grid_section(status.grid)]
    parts.append("<h2>Files</h2>\n<table>\n<tr>")
    parts.append("".join(f"<th>{esc(h)}</th>" for h in _ROW_HEADERS))
    parts.append("</tr>\n")
    parts.extend(_file_row(r) for r in files)
    parts.append("</table>\n</body></html>\n")
    return "".join(parts)
