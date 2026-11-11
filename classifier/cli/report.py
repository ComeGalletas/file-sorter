"""`classifier report [--out]`: the self-contained HTML report (CLI-008.2; R-API-7, §7).

A thin wrapper: one read-only, repeatable-read transaction builds API-001's `StatusView`
and `FileRow`s, `render_report` (API-001.5) turns them into HTML, and the file is written
once, opened exclusively, so nothing is ever overwritten. The default target is
`results_root/reports/report-<UTC timestamp>.html` (API-001.D6); a same-second clash gets
`-1`, `-2`, like the dry-run CSV. The report makes no Ollama call, so the loaded models stay
"n/a" (CLI-008.D1). It holds sanitized names and hashes only, never `source_path`.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import typer
from sqlalchemy import text

from classifier.api.app import read_only_engine
from classifier.api.report import render_report
from classifier.api.views import FileFilters, build_status, file_row, rows_query
from classifier.config import ConfigError, load_config

# CLI-008.2.1: fixed, as categories.py's; load_config's own texts can carry the path.
CONFIG_FAILED = "error: the config could not be loaded; check the config file and DB_DSN"
DB_FAILED = "error: database error, see the db service logs"
WRITE_FAILED = "error: could not write the report"
OUT_EXISTS = "error: --out already exists; choose a new file"


def report_path(results_root: str, stamp: datetime, attempt: int = 0) -> Path:
    """`results_root/reports/report-<UTC timestamp>[-<attempt>].html` (API-001.D6)."""
    suffix = f"-{attempt}" if attempt else ""
    return Path(results_root) / "reports" / f"report-{stamp:%Y%m%dT%H%M%SZ}{suffix}.html"


def _render(dsn: str) -> str:
    engine = read_only_engine(dsn)
    try:
        with engine.connect() as conn:
            # One snapshot, so the status and the rows agree (as the API's reads do).
            conn.execute(text("set transaction isolation level repeatable read, read only"))
            status = build_status(conn)  # loaded_models stays "n/a" (CLI-008.D1)
            rows = (file_row(m) for m in conn.execute(rows_query(FileFilters())).mappings())
            return render_report(status, rows)
    finally:
        engine.dispose()


def _write_new(path: Path, data: bytes) -> None:
    """Create `path` exclusively and write `data`; FileExistsError if it is there."""
    with path.open("xb") as handle:
        handle.write(data)


def _write_default(results_root: str, stamp: datetime, data: bytes) -> Path:
    folder = report_path(results_root, stamp).parent
    folder.mkdir(parents=True, exist_ok=True)
    attempt = 0
    while True:
        path = report_path(results_root, stamp, attempt)
        try:
            _write_new(path, data)
        except FileExistsError:
            attempt += 1
            continue
        return path


def report(
    out: Annotated[
        Path | None,
        typer.Option("--out", help="Write here instead; refused if the file exists."),
    ] = None,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Config file; default $CLASSIFIER_CONFIG.")
    ] = None,
) -> None:
    """Write the HTML report of the ledger (sanitized names and hashes only)."""
    config = None
    try:
        config = load_config(config_path)
    except ConfigError:  # CLI-008.2.1: its text can carry the --config path
        pass
    if config is None or not config.db.dsn:
        typer.echo(CONFIG_FAILED, err=True)
        raise typer.Exit(2)
    dsn = config.db.dsn
    stamp = datetime.now(UTC)

    db_failed = False
    try:
        html = _render(dsn)
    except Exception:  # noqa: BLE001 — CLI-008.2.1: any message may carry the DSN or a value
        db_failed = True
    if db_failed:
        typer.echo(DB_FAILED, err=True)
        raise typer.Exit(1)

    exists = write_failed = False
    target: Path | None = None
    try:
        data = html.encode("utf-8")  # strict: sanitized names are valid text
        if out is not None:
            try:
                _write_new(out, data)
                target = out
            except FileExistsError:  # only --out's own file; never overwritten
                exists = True
        else:
            # Here a FileExistsError (a file where `reports/` goes) is a write failure.
            target = _write_default(config.paths.results_root, stamp, data)
    except (OSError, UnicodeError):  # an OSError message carries the path: fixed text
        write_failed = True
    if exists:
        typer.echo(OUT_EXISTS, err=True)
        raise typer.Exit(2)
    if write_failed or target is None:
        typer.echo(WRITE_FAILED, err=True)
        raise typer.Exit(1)
    typer.echo(f"report written: {target.name}")
