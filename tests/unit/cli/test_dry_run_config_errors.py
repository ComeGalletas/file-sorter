"""CFG-002.1.4: `dry-run` exits 2 on a bad config without echoing a value, with no database."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from classifier.cli import app
from classifier.graph.sanitize import WorkDirError, prepare_folders
from classifier.sanitize.rules import SanitizeConfigError, load_rules

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


# SAN-003.3: filesystem OSErrors end in fixed text and exit 2, never a traceback.
SECRET_DIR = "/qorvex-zhyndel-san0033"
RULES_FILE = "sanitize-qorvex.yaml"


def _oserror(code: int = 13) -> OSError:
    return OSError(code, "denied", f"{SECRET_DIR}/zhyndel.yaml")


def _assert_fixed_exit(result, expected: str) -> None:
    assert result.exit_code == 2, result.output
    assert expected in result.stderr
    for stream in (result.stdout, result.stderr, result.output):
        assert SECRET_DIR not in stream
        assert "zhyndel" not in stream
        assert "Traceback" not in stream
    assert isinstance(result.exception, SystemExit)
    link = result.exception  # typer's own Exit(2) may sit in the chain; nothing else may
    while link is not None:
        assert not isinstance(link, OSError)
        assert SECRET_DIR not in str(link)
        link = link.__cause__ or link.__context__


def _config_file(tmp_path: Path) -> Path:
    data = _data()
    data["sanitizer"]["rules_file"] = str(tmp_path / RULES_FILE)
    data["paths"]["source_root"] = str(tmp_path / "src")
    data["paths"]["results_root"] = str(tmp_path / "res")
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    (tmp_path / "src").mkdir()
    (tmp_path / "res").mkdir()
    (tmp_path / RULES_FILE).write_text("rules: []\n", encoding="utf-8")
    return config


def _invoke_with(config: Path, monkeypatch, fake_run):
    monkeypatch.setattr("classifier.cli.run", fake_run)
    return CliRunner().invoke(
        app, ["dry-run", "--config", str(config)], env={"DB_DSN": "postgresql://u:p@db/x"}
    )


def test_rules_read_oserror_exits_2_with_fixed_text(tmp_path: Path, monkeypatch) -> None:
    config = _config_file(tmp_path)
    real = Path.read_text

    def read_text(self, *args, **kwargs):
        if self.name == RULES_FILE:
            raise _oserror()
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read_text)
    result = _invoke_with(
        config, monkeypatch, lambda cfg, dry_run: load_rules(cfg.sanitizer.rules_file)
    )
    _assert_fixed_exit(result, "error: rules file can't be read (sanitizer.rules_file)")


def test_rules_read_oserror_is_unchained(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / RULES_FILE).write_text("rules: []\n", encoding="utf-8")

    def read_text(self, *args, **kwargs):
        raise _oserror()

    monkeypatch.setattr(Path, "read_text", read_text)
    with pytest.raises(SanitizeConfigError) as caught:
        load_rules(tmp_path / RULES_FILE)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET_DIR not in str(caught.value)
    assert "zhyndel" not in str(caught.value)


def _prepare(cfg, dry_run):
    prepare_folders(Path(cfg.paths.source_root), Path(cfg.paths.results_root))


def test_thumbs_mkdir_oserror_exits_2_with_fixed_text(tmp_path: Path, monkeypatch) -> None:
    config = _config_file(tmp_path)
    real = Path.mkdir

    def mkdir(self, *args, **kwargs):
        if self.name == "thumbs":
            raise _oserror()
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    result = _invoke_with(config, monkeypatch, _prepare)
    _assert_fixed_exit(result, "error: results_root/.work/thumbs could not be created")


@pytest.mark.parametrize("failure", [_oserror(), RuntimeError(f"Symlink loop from {SECRET_DIR}")])
def test_resolve_failure_exits_2_with_fixed_text(tmp_path: Path, monkeypatch, failure) -> None:
    config = _config_file(tmp_path)

    def resolve(self, *args, **kwargs):
        raise failure

    monkeypatch.setattr(Path, "resolve", resolve)
    result = _invoke_with(config, monkeypatch, _prepare)
    _assert_fixed_exit(result, "error: results_root or source_root could not be resolved")


@pytest.mark.parametrize("target", ["source", "results", "thumbs"])
def test_prepare_folders_errors_are_unchained(tmp_path: Path, monkeypatch, target: str) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "res").mkdir()
    real_resolve, real_mkdir = Path.resolve, Path.mkdir

    def resolve(self, *args, **kwargs):
        if (target == "source" and self.name == "src") or (
            target == "results" and self.name == "res"
        ):
            raise _oserror()
        return real_resolve(self, *args, **kwargs)

    def mkdir(self, *args, **kwargs):
        if target == "thumbs" and self.name == "thumbs":
            raise _oserror()
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", resolve)
    monkeypatch.setattr(Path, "mkdir", mkdir)
    with pytest.raises(WorkDirError) as caught:
        prepare_folders(tmp_path / "src", tmp_path / "res")
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert SECRET_DIR not in str(caught.value)
    assert "zhyndel" not in str(caught.value)
