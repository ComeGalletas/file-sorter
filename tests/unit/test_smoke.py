"""RUN-001.4: the package imports, the CLI answers, and tiers are assigned by path."""

from typer.testing import CliRunner

import classifier
from classifier.cli import app


def test_cli_version_matches_package() -> None:
    result = CliRunner().invoke(app, ["version"])
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == classifier.__version__


def test_this_module_is_tiered_unit(request) -> None:
    assert request.node.get_closest_marker("unit") is not None
    assert request.node.get_closest_marker("db") is None
