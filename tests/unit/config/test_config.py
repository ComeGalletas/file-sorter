"""CFG-001.1: typed config loading and the R-FOP-9 root check."""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from classifier.config import Config, ConfigError, check_roots, load_config

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


def test_null_dsn_in_the_file_falls_back_to_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    data = real_data()
    data["db"] = {"dsn": None}
    assert load_config(write_config(tmp_path, data)).db.dsn == FAKE_DSN


def test_load_rejects_non_mapping(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    file = tmp_path / "config.yaml"
    file.write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="mapping"):
        load_config(file)


def with_roots(source: str, results: str) -> Config:
    data = real_data()
    data["paths"] = {"source_root": source, "results_root": results}
    return Config.model_validate(data)


def test_real_roots_pass_the_check() -> None:
    check_roots(Config.model_validate(real_data()))


@pytest.mark.parametrize(
    ("source", "results"),
    [
        ("/data", "/data"),
        ("/data", "/data/"),
        ("/data", "/data/results"),
        ("/data/source", "/data"),
        ("/data", "/data/sub/../results"),
        ("/data/a/..", "/data/results"),
        ("/data//", "/data/results/"),
        ("/data/source", "/data/source/../.."),
    ],
)
def test_nested_or_equal_roots_are_refused(source: str, results: str) -> None:
    with pytest.raises(ConfigError, match="R-FOP-9"):
        check_roots(with_roots(source, results))


@pytest.mark.parametrize(
    ("source", "results"),
    [
        ("/results", "/results2"),
        ("/data/source", "/data/source-out"),
        ("/data/a/../source", "/data/results"),
    ],
)
def test_sibling_roots_pass(source: str, results: str) -> None:
    check_roots(with_roots(source, results))


def test_load_config_refuses_nested_roots(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    data = real_data()
    data["paths"]["results_root"] = "/source/out"
    with pytest.raises(ConfigError, match="R-FOP-9"):
        load_config(write_config(tmp_path, data))


# CFG-002.1.1: load errors carry no value from the file, and no exception chain.

PLANTED = "PLANTED-SECRET-cfg002"
PLANTED_INT = 424242987


def assert_value_free(error: ConfigError) -> None:
    assert PLANTED not in str(error)
    assert PLANTED not in repr(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def load_error(file: Path) -> ConfigError:
    with pytest.raises(ConfigError) as info:
        load_config(file)
    return info.value


def test_invalid_yaml_names_the_line_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    file = tmp_path / "config.yaml"
    file.write_text(f"paths:\n  source_root: [{PLANTED}\n", encoding="utf-8")
    error = load_error(file)
    assert "not valid YAML at line" in str(error)
    assert_value_free(error)


def test_non_utf8_file_is_refused_without_its_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    file = tmp_path / "config.yaml"
    file.write_bytes(PLANTED.encode() + b"\xff\xfe\n")
    error = load_error(file)
    assert "not UTF-8" in str(error)
    assert_value_free(error)


def test_invalid_value_names_the_key_and_type_only(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    data = real_data()
    data["classify"]["score"] = PLANTED
    data["thumbs"]["size"] = PLANTED
    error = load_error(write_config(tmp_path, data))
    assert "classify.score: literal_error" in str(error)
    assert "thumbs.size: int_parsing" in str(error)
    assert_value_free(error)


def test_unknown_key_is_not_named(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    data = real_data()
    data["paths"][PLANTED] = PLANTED
    data[PLANTED] = 1
    data["thumbs"][PLANTED_INT] = 1  # int and bool YAML keys stay int in pydantic's loc
    data["watch"][True] = 1
    file = tmp_path / "config.yaml"
    file.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")  # mixed key types
    error = load_error(file)
    assert "paths.<unknown key>: extra_forbidden" in str(error)
    assert "thumbs.<unknown key>: invalid_key" in str(error)
    assert "watch.<unknown key>: invalid_key" in str(error)
    assert_value_free(error)
    for text in (str(error), repr(error)):
        assert str(PLANTED_INT) not in text
        assert "True" not in text


def test_unreadable_file_is_a_fixed_unchained_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("DB_DSN", FAKE_DSN)
    file = write_config(tmp_path, real_data())

    def refuse(self: Path, *args: object, **kwargs: object) -> str:
        raise PermissionError(13, PLANTED)

    monkeypatch.setattr(Path, "read_text", refuse)
    error = load_error(file)
    assert "can't be read" in str(error)
    assert_value_free(error)


# CFG-002.1.2: absolute roots only, a leading `//` collapsed, no path in the message.


@pytest.mark.parametrize(
    ("source", "results"),
    [
        ("//data", "/data/results"),
        ("/data", "//data/results"),
        ("//data", "//data"),
        ("//data/source", "/data/source/"),
    ],
)
def test_leading_double_slash_is_collapsed(source: str, results: str) -> None:
    with pytest.raises(ConfigError, match="nested"):
        check_roots(with_roots(source, results))


def test_double_slash_siblings_pass() -> None:
    check_roots(with_roots("//source", "/results"))


@pytest.mark.parametrize(
    ("source", "results"),
    [
        ("source", "results"),
        ("source", "/results"),
        ("/source", "results"),
        ("./source", "/results"),
        ("", "/results"),
    ],
)
def test_relative_or_mixed_roots_are_refused(source: str, results: str) -> None:
    with pytest.raises(ConfigError, match="absolute") as info:
        check_roots(with_roots(source, results))
    assert info.value.__cause__ is None


@pytest.mark.parametrize(
    ("source", "results"),
    [(f"/{PLANTED}", f"/{PLANTED}/out"), (PLANTED, "/results")],
)
def test_root_errors_name_the_keys_not_the_paths(source: str, results: str) -> None:
    with pytest.raises(ConfigError) as info:
        check_roots(with_roots(source, results))
    assert "paths.source_root" in str(info.value)
    assert PLANTED not in str(info.value)
    assert PLANTED not in repr(info.value)


# CFG-002.1.3: CFG-001.D2, DB_DSN always wins and a DSN in the file is refused.

PLANTED_DSN = f"postgresql://user:{PLANTED}@db:5432/x"  # placeholder, not a real DSN


@pytest.mark.parametrize("env_dsn", [FAKE_DSN, None])
@pytest.mark.parametrize("file_dsn", [PLANTED_DSN, ""])
def test_dsn_in_the_file_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, env_dsn: str | None, file_dsn: str
) -> None:
    if env_dsn is None:
        monkeypatch.delenv("DB_DSN", raising=False)
    else:
        monkeypatch.setenv("DB_DSN", env_dsn)
    data = real_data()
    data["db"]["dsn"] = file_dsn
    error = load_error(write_config(tmp_path, data))
    assert "db.dsn must be null" in str(error)
    assert "DB_DSN" in str(error)
    assert_value_free(error)


def test_dsn_is_not_in_the_config_repr(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_DSN", PLANTED_DSN)
    config = load_config(REAL_CONFIG)
    assert config.db.dsn == PLANTED_DSN
    assert PLANTED not in repr(config)
    assert PLANTED not in str(config)
    assert PLANTED not in repr(config.db)
