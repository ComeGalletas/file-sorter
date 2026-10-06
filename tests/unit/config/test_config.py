"""CFG-001.1: typed config loading and the R-FOP-9 root check."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from classifier.config import Config

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
