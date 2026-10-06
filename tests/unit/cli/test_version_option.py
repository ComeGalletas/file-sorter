"""CLI-001.1: `classifier --version` prints the package version and exits 0."""

from typer.testing import CliRunner

import classifier
from classifier.cli import app


def test_version_option_prints_package_version() -> None:
    result = CliRunner().invoke(app, ["--version"])
    assert result.exit_code == 0, result.output
    assert result.stdout == f"{classifier.__version__}\n"


def test_this_module_is_tiered_unit(request) -> None:
    assert request.node.get_closest_marker("unit") is not None
