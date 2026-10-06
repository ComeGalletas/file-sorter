"""Typer CLI (DESIGN.md §7). Commands land milestone by milestone."""

import typer

from classifier import __version__

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
