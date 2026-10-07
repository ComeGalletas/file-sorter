"""CFG-002.1.4: `dry-run` exits 2 on a bad config without echoing a value, with no database."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from classifier.cli import app

REAL_CONFIG = Path(__file__).resolve().parents[3] / "config.yaml"
PLANTED = "PLANTED-SECRET-cfg002"
PLANTED_INT = 424242987
PLANTED_DSN = f"postgresql://user:{PLANTED}@db:5432/x"  # placeholder, not a real DSN


def _invoke(tmp_path: Path, data: dict, dsn: str | None = "postgresql://u:p@db/x"):
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return CliRunner().invoke(app, ["dry-run", "--config", str(config)], env={"DB_DSN": dsn})


def _data() -> dict:
    return yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))


def _assert_value_free_exit(result, expected: str) -> None:
    assert result.exit_code == 2, result.output
    assert expected in result.output
    assert PLANTED not in result.output
    assert "Traceback" not in result.output


def test_invalid_value_exits_2_naming_the_key_only(tmp_path: Path) -> None:
    data = _data()
    data["thumbs"]["size"] = PLANTED
    data["paths"][PLANTED] = PLANTED
    data["api"][PLANTED_INT] = 1
    data["watch"][True] = 1
    result = _invoke(tmp_path, data)
    _assert_value_free_exit(result, "thumbs.size: int_parsing")
    assert "paths.<unknown key>" in result.output
    assert "api.<unknown key>" in result.output
    assert str(PLANTED_INT) not in result.stderr
    assert "True" not in result.stderr


def test_invalid_yaml_exits_2_without_the_text(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    config.write_text(f"paths: [{PLANTED}\n", encoding="utf-8")
    result = CliRunner().invoke(app, ["dry-run", "--config", str(config)])
    _assert_value_free_exit(result, "not valid YAML")


@pytest.mark.parametrize("env_dsn", ["postgresql://u:p@db/x", None])
def test_dsn_in_the_file_exits_2_without_the_dsn(tmp_path: Path, env_dsn: str | None) -> None:
    data = _data()
    data["db"]["dsn"] = PLANTED_DSN
    result = _invoke(tmp_path, data, env_dsn)
    _assert_value_free_exit(result, "db.dsn must be null")


def test_this_module_is_tiered_unit(request) -> None:
    assert request.node.get_closest_marker("unit") is not None
