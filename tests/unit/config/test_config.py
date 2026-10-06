"""CFG-001.1: typed config loading and the R-FOP-9 root check."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from classifier.config import Config, ConfigError, load_config

REPO = Path(__file__).resolve().parents[3]
REAL_CONFIG = REPO / "config.yaml"


def real_data() -> dict:
    return yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))


def test_real_config_validates() -> None:
    config = Config.model_validate(real_data())
    assert config.paths.source_root == "/source"
    assert config.paths.results_root == "/results"


def test_undecided_values_stay_none() -> None:
    config = Config.model_validate(real_data())
    assert config.models.vlm_nsfw is None
    assert config.classify.format.default_min_score is None
    assert config.classify.topic.default_min_score is None
    assert config.db.dsn is None


def test_deletion_defaults_to_disabled() -> None:
    data = real_data()
    del data["deletion"]
    assert Config.model_validate(data).deletion.enabled is False
    assert Config.model_validate(real_data()).deletion.enabled is False


def test_unknown_top_level_key_is_an_error() -> None:
    data = real_data()
    data["surprise"] = 1
    with pytest.raises(ValidationError, match="surprise"):
        Config.model_validate(data)


def test_unknown_section_key_is_an_error() -> None:
    data = real_data()
    data["paths"]["extra_root"] = "/x"
    with pytest.raises(ValidationError, match="extra_root"):
        Config.model_validate(data)


def test_invalid_choice_is_an_error() -> None:
    data = real_data()
    data["classify"]["score"] = "euclid"
    with pytest.raises(ValidationError, match="score"):
        Config.model_validate(data)


FAKE_DSN = "postgresql://user:pw@db:5432/test"  # placeholder, not a real DSN


def write_config(tmp_path: Path, data: dict) -> Path:
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(data), encoding="utf-8")
    return file


def test_load_real_config_takes_dsn_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    config = load_config(REAL_CONFIG)
    assert config.db.dsn == FAKE_DSN


def test_load_reads_path_from_classifier_config(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CLASSIFIER_CONFIG", str(write_config(tmp_path, real_data())))
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    assert load_config().paths.source_root == "/source"


def test_load_without_any_path_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CLASSIFIER_CONFIG", raising=False)
    with pytest.raises(ConfigError, match="CLASSIFIER_CONFIG"):
        load_config()


def test_load_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml")


def test_load_without_dsn_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_DSN", raising=False)
    with pytest.raises(ConfigError, match="DB_DSN"):
        load_config(REAL_CONFIG)


def test_load_prefers_dsn_in_the_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    data = real_data()
    data["db"]["dsn"] = "postgresql://other/x"
    assert load_config(write_config(tmp_path, data)).db.dsn == "postgresql://other/x"


def test_load_rejects_non_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    file = tmp_path / "config.yaml"
    file.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(file)
