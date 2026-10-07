"""SAN-001.1: load sanitize.yaml (SAN-001.D1, D5, D11). Synthetic values only."""

from pathlib import Path

import pytest
import yaml

from classifier.sanitize.rules import (
    LOG_KEY_ENV,
    EntityRule,
    ExifFieldRule,
    LiteralRule,
    RegexRule,
    SanitizeConfigError,
    load_rules,
    log_key,
)

KEY = "00112233445566778899aabbccddeeff"
ENV = {LOG_KEY_ENV: KEY}
SECRET = "Zyxwq Plonk"  # a made-up value that must never surface in an error message


def rules_data() -> dict:
    return {
        "exif": {"mode": "strip_all", "keep": ["Orientation", "DateTimeOriginal"]},
        "rules": [
            {"id": "who", "type": "literal", "values": [SECRET], "replace": "[PERSON]"},
            {"id": "mail", "type": "regex", "pattern": r"\w+@\w+\.\w+", "replace": "[EMAIL]"},
            {"id": "ner", "type": "entity", "labels": ["PERSON", "ORG"], "replace": "[{label}]"},
            {"id": "gps", "type": "exif_field", "fields": ["GPSLatitude", "SerialNumber"]},
        ],
    }


def write(tmp_path: Path, data: object) -> Path:
    path = tmp_path / "sanitize.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def load_error(tmp_path: Path, data: object, env: dict | None = None) -> str:
    with pytest.raises(SanitizeConfigError) as info:
        load_rules(write(tmp_path, data), env=ENV if env is None else env)
    message = str(info.value)
    assert "make init" in message
    assert "Zyxwq" not in message and "Plonk" not in message
    # No chained exception in the traceback: pydantic's and YAML's errors quote the input.
    assert info.value.__cause__ is None
    assert info.value.__context__ is None or info.value.__suppress_context__
    return message


def test_valid_file_loads_into_typed_rules(tmp_path: Path) -> None:
    rules = load_rules(write(tmp_path, rules_data()), env=ENV)
    assert rules.exif.keep == ["Orientation", "DateTimeOriginal"]
    assert [type(rule) for rule in rules.rules] == [
        LiteralRule,
        RegexRule,
        EntityRule,
        ExifFieldRule,
    ]
    assert rules.of_type(ExifFieldRule)[0].fields == ["GPSLatitude", "SerialNumber"]
    assert rules.log_key == KEY.encode("utf-8")


def test_the_key_never_appears_in_repr(tmp_path: Path) -> None:
    rules = load_rules(write(tmp_path, rules_data()), env=ENV)
    assert KEY not in repr(rules)


def test_the_example_file_loads() -> None:
    example = Path(__file__).resolve().parents[3] / "sanitize.example.yaml"
    rules = load_rules(example, env=ENV)
    assert rules.exif.mode == "strip_all"


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(SanitizeConfigError, match="make init"):
        load_rules(tmp_path / "absent.yaml", env=ENV)


@pytest.mark.parametrize("content", ["", "- just\n- a list\n"])
def test_empty_or_non_mapping_file(tmp_path: Path, content: str) -> None:
    path = tmp_path / "sanitize.yaml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(SanitizeConfigError, match="make init"):
        load_rules(path, env=ENV)


def test_broken_yaml_never_quotes_the_file(tmp_path: Path) -> None:
    path = tmp_path / "sanitize.yaml"
    path.write_text(f"rules:\n  - values: [{SECRET}\n  bad: : :\n", encoding="utf-8")
    with pytest.raises(SanitizeConfigError) as info:
        load_rules(path, env=ENV)
    assert "make init" in str(info.value) and "line" in str(info.value)
    assert "Zyxwq" not in str(info.value)


def test_unknown_key(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][0][SECRET] = 1
    assert "rules[0].<unknown key>" in load_error(tmp_path, data)


def test_missing_exif_section(tmp_path: Path) -> None:
    data = rules_data()
    del data["exif"]
    assert "exif: missing" in load_error(tmp_path, data)


def test_unknown_rule_type(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][0]["type"] = "Zyxwq"
    assert "rules[0]" in load_error(tmp_path, data)


def test_bad_regex_names_the_key_not_the_pattern(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][1]["pattern"] = "[Zyxwq Plonk"
    assert "rules[1].pattern: invalid regex" in load_error(tmp_path, data)


def test_duplicate_rule_ids(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][1]["id"] = "who"
    assert "unique" in load_error(tmp_path, data)


def test_unknown_entity_label(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][2]["labels"] = ["Zyxwq"]
    assert "rules[2].labels[0]" in load_error(tmp_path, data)


def test_entity_replace_takes_only_the_label_placeholder(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][2]["replace"] = "[{Zyxwq}]"
    assert "rules[2].replace" in load_error(tmp_path, data)


@pytest.mark.parametrize("value", ["", " _-."])
def test_literal_value_needs_text(tmp_path: Path, value: str) -> None:
    data = rules_data()
    data["rules"][0]["values"] = [SECRET, value]
    assert "rules[0].values" in load_error(tmp_path, data)


def test_wrong_value_type_never_echoes_the_value(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][0]["replace"] = {SECRET: SECRET}
    assert "rules[0].replace" in load_error(tmp_path, data)


@pytest.mark.parametrize("env", [{}, {LOG_KEY_ENV: ""}, {LOG_KEY_ENV: "  "}])
def test_missing_log_key(tmp_path: Path, env: dict) -> None:
    message = load_error(tmp_path, rules_data(), env=env)
    assert LOG_KEY_ENV in message


def test_log_key_reads_the_process_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(LOG_KEY_ENV, KEY)
    assert log_key() == KEY.encode("utf-8")
