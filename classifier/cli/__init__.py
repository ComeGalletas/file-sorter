"""Typer CLI (DESIGN.md §7). Commands land milestone by milestone.

`classifier dry-run` console contract (CLI-005.1; gate 3 may parse it). Counts and fixed
reason codes only: never a path, a name, a category, a score. Lines, in this order, each
`label: integer` unless noted; the `ledger skipped`, `sanitize error` and `classify error`
lines repeat once per fixed reason, sorted, and are absent when there is none:

    run <8 hex> (dry run)
    new / skipped-known / skipped-unreadable / duplicates / total      (ingest)
    ledger skipped, <reason>: N
    sanitized / sanitize errors                                       (sanitize)
    sanitize error, <reason>: N
    classified / unsorted / no topic / adult / classify errors          (classify)
    classify error, <reason>: N
    report: <file name> (<rows> rows)                                 (only with --csv)

`unsorted`, `no topic` and `adult` are subsets of `classified`. Errors go to stderr as
`error: <fixed text>` with exit 2 (config, pre-flight, folders) or 1 (database).
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

import psycopg
import typer

from classifier import __version__
from classifier.cli import dry_run_report
from classifier.cli.categories import categories_app
from classifier.config import ConfigError, load_config
from classifier.graph.classify import ClassifyConfigError
from classifier.graph.run import run
from classifier.graph.sanitize import WorkDirError
from classifier.models.classify_rules import ClassifyRulesError
from classifier.models.ollama import OllamaError
from classifier.models.vision import VisionError
from classifier.sanitize.rules import SanitizeConfigError

app = typer.Typer(no_args_is_help=True, add_completion=False, help="file-sorter image classifier.")
app.add_typer(categories_app, name="categories")


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
    except ConfigError as error:  # value-free: load_config wraps YAML and validation errors
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from None
    started = datetime.now(UTC)
    try:
        result = run(config, dry_run=True)
        with psycopg.connect(dsn) as conn:
            rows = dry_run_report.rows_under_root(conn, config.paths.source_root)
            folder_of = dry_run_report.folder_resolver(conn, config)
    except (
        SanitizeConfigError,
        WorkDirError,
        ClassifyConfigError,
        ClassifyRulesError,
        VisionError,
    ) as error:
        # CLI-003.1.3, CLI-005.1: the pre-flights; fixed text naming the key (SAN-001.D6, D16,
        # CLS-002.D9). The failing node rolled back; earlier nodes' commits stay.
        typer.echo(f"error: {error}", err=True)
        raise typer.Exit(2) from None
    except OllamaError:
        # Fixed text: the pre-flight `from_env` (OLLAMA_HOST unset) is the one that reaches here.
        typer.echo("error: the Ollama client could not start; is OLLAMA_HOST set?", err=True)
        raise typer.Exit(2) from None
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
    sanitized = result.sanitize  # CLI-003.1: counts and the fixed SAN-001.D17 reasons only
    typer.echo(f"sanitized: {sanitized.sanitized}")
    typer.echo(f"sanitize errors: {sanitized.errored}")
    for reason, count in sorted(sanitized.by_reason.items()):
        typer.echo(f"sanitize error, {reason}: {count}")
    classified = result.classify  # CLI-005.1: counts and the fixed CLS-002.D7 reasons only
    typer.echo(f"classified: {classified.classified}")
    typer.echo(f"unsorted: {classified.unsorted}")
    typer.echo(f"no topic: {classified.no_topic}")
    typer.echo(f"adult: {classified.adult}")
    typer.echo(f"classify errors: {classified.errored}")
    for reason, count in sorted(classified.by_reason.items()):
        typer.echo(f"classify error, {reason}: {count}")
    if csv:
        try:
            target = dry_run_report.write_csv(config.paths.results_root, started, rows, folder_of)
        except dry_run_report.ReportWriteError as error:
            # SAN-003.3: run has committed, so the ledger is written; a re-run rebuilds the report.
            # CLI-005.1: a ReportFolderError lands here too.
            typer.echo(f"error: {error}", err=True)
            raise typer.Exit(2) from None
        typer.echo(f"report: {target.name} ({len(rows)} rows)")
