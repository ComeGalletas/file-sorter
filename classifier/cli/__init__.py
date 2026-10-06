"""Typer CLI (DESIGN.md §7). Commands land milestone by milestone."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import psycopg
import typer
from pydantic import ValidationError

from classifier import __version__
from classifier.cli import dry_run_report
from classifier.config import ConfigError, load_config
from classifier.graph.run import run

app = typer.Typer(no_args_is_help=True, add_completion=False, help="file-sorter image classifier.")


def _print_version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    _version: bool = typer.Option(  # CLI-001.D1: eager, so it runs without a subcommand
        False,
        "--version",
        callback=_print_version,
        is_eager=True,
        help="Print the package version and exit.",
    ),
) -> None:
    """Keep `classifier` a command group even while it has a single command."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command("dry-run")
def dry_run(
    csv: Annotated[
        bool, typer.Option("--csv", help="Write results_root/reports/dry-run-<timestamp>.csv.")
    ] = False,
    config_path: Annotated[
        Path | None, typer.Option("--config", help="Config file; default $CLASSIFIER_CONFIG.")
    ] = None,
) -> None:
    """Run every node except fileops over the source and report what the ledger holds."""
    try:
        config = load_config(config_path)  # runs the root check (R-FOP-9)
        dsn = config.db.dsn
        if not dsn:
            raise ConfigError("config.db.dsn is not set")
    except ConfigError as error:
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from error
    except ValidationError as error:
        # Only the field names: a validation message echoes the offending values.
        fields = sorted({".".join(str(part) for part in e["loc"]) for e in error.errors()})
        typer.echo(f"error: invalid config, check: {', '.join(fields)}", err=True)
        raise typer.Exit(2) from None
    started = datetime.now(UTC)
    try:
        result = run(config, dry_run=True)
        with psycopg.connect(dsn) as conn:
            rows = dry_run_report.rows_under_root(conn, config.paths.source_root)
    except psycopg.Error:
        # Fixed text: a driver message can carry the DSN or a path.
        typer.echo("error: database error, see the db service logs", err=True)
        raise typer.Exit(1) from None
    counts = result.ingest
    typer.echo(f"run {result.run_id[:8]} (dry run)")
    typer.echo(f"new: {counts.new}")
    typer.echo(f"skipped-known: {counts.skipped_known}")
    typer.echo(f"skipped-unreadable: {counts.skipped_unreadable}")
    typer.echo(f"duplicates: {counts.duplicate}")
    typer.echo(f"total: {counts.total}")
    for reason, count in dry_run_report.skip_reasons(rows).items():
        typer.echo(f"ledger skipped, {reason}: {count}")
    if csv:
        target = dry_run_report.write_csv(config.paths.results_root, started, rows)
        typer.echo(f"report: {target.name} ({len(rows)} rows)")
