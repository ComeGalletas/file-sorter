"""Typer CLI (DESIGN.md §7). Commands land milestone by milestone."""

import typer

from classifier import __version__

app = typer.Typer(no_args_is_help=True, add_completion=False, help="file-sorter image classifier.")


@app.callback()
def main() -> None:
    """Keep `classifier` a command group even while it has a single command."""


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)
