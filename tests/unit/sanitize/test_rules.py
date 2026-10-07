"""SAN-001.1: load sanitize.yaml and redact text (SAN-001.D1, D5, D11). Synthetic values only."""

import hashlib
import hmac
from collections.abc import Sequence
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from classifier.sanitize.rules import (
    FILENAME,
    LOG_KEY_ENV,
    PATH_SEGMENT,
    EntityRule,
    ExifFieldRule,
    LiteralRule,
    Redaction,
    RegexRule,
    Rules,
    RulesFile,
    SanitizeConfigError,
    before_hash,
    load_rules,
    log_key,
    sanitize_name,
    sanitize_text,
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
    assert_unchained(info.value)
    return message


def assert_unchained(error: BaseException) -> None:
    # Not even a suppressed __context__: pydantic's, YAML's and re's errors quote the input.
    assert error.__cause__ is None
    assert error.__context__ is None


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


PATTERN_SECRET = "Qwvplk"  # a made-up value embedded in a regex


def test_repr_and_str_never_show_values_patterns_or_fields(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][1]["pattern"] = rf"{PATTERN_SECRET}\d+"
    data["rules"][3]["fields"] = ["Zyxwqtag"]
    data["exif"]["keep"] = ["Orientation", "PlonkKeep"]  # tag-shaped, so it loads
    for index in (0, 1, 2):
        data["rules"][index]["replace"] = "[Zyxwq Plonk]"
    rules = load_rules(write(tmp_path, data), env=ENV)
    shown = [repr(rules), str(rules)]
    shown += [text for rule in rules.rules for text in (repr(rule), str(rule))]
    shown += [repr(list(rules.rules)), repr(RulesFile.model_validate(data))]
    shown += [repr(rules.exif), str(rules.exif)]
    for text in shown:
        for secret in ("Zyxwq", "Plonk", PATTERN_SECRET, KEY):
            assert secret not in text, text
    # Ids and types stay visible, so a printed Rules is still useful.
    assert repr(rules).endswith("rules=[who:literal, mail:regex, ner:entity, gps:exif_field])")


@pytest.mark.parametrize("where", ["keep", "fields"])
@pytest.mark.parametrize("bad", [SECRET, "Zyxwq@Plonk", "1Zyxwq", "Zyxwq" * 13, ""])
def test_tag_lists_take_tag_names_only(tmp_path: Path, where: str, bad: str) -> None:
    data = rules_data()
    if where == "keep":
        data["exif"]["keep"] = ["Orientation", bad]
    else:
        data["rules"][3]["fields"] = [bad]
    location = "exif.keep[1]" if where == "keep" else "rules[3].fields[0]"
    assert f"{location}: string_pattern_mismatch" in load_error(tmp_path, data)


def test_tag_names_with_a_group_prefix_load(tmp_path: Path) -> None:
    data = rules_data()
    data["exif"]["keep"] = ["Orientation", "EXIF:DateTimeOriginal", "XMP-dc_Rights"]
    assert load_rules(write(tmp_path, data), env=ENV).exif.keep[1] == "EXIF:DateTimeOriginal"


def test_non_utf8_file_never_echoes_its_bytes(tmp_path: Path) -> None:
    path = tmp_path / "sanitize.yaml"
    path.write_bytes(b"rules:\n  - values: [Zyxwq\xff\xfePlonk]\n")
    with pytest.raises(SanitizeConfigError) as info:
        load_rules(path, env=ENV)
    assert "make init" in str(info.value) and "UTF-8" in str(info.value)
    assert "Zyxwq" not in str(info.value) and "0xff" not in str(info.value)
    assert_unchained(info.value)


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
    assert_unchained(info.value)


def test_bad_regex_error_carries_no_chained_re_error(tmp_path: Path) -> None:
    data = rules_data()
    data["rules"][1]["pattern"] = f"[{PATTERN_SECRET}"
    with pytest.raises(SanitizeConfigError) as info:
        load_rules(write(tmp_path, data), env=ENV)
    assert PATTERN_SECRET not in str(info.value)
    assert_unchained(info.value)
    # The validator's own ValueError is raised outside its except block too.
    with pytest.raises(ValidationError) as raw:
        RegexRule.model_validate(data["rules"][1])
    inner = raw.value.errors()[0]["ctx"]["error"]
    assert_unchained(inner)
    assert PATTERN_SECRET not in repr(inner)


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


# --- sanitize_text / sanitize_name (SAN-001.D1, R-SAN-4, R-SAN-6) ------------------------


def make_rules(*rules: dict, key: str = KEY) -> Rules:
    data = {"exif": {"mode": "strip_all"}, "rules": list(rules)}
    parsed = RulesFile.model_validate(data)
    return Rules(exif=parsed.exif, rules=tuple(parsed.rules), log_key=key.encode("utf-8"))


WHO = {"id": "who", "type": "literal", "values": ["zyxwq plonk"], "replace": "[PERSON]"}
MAIL = {"id": "mail", "type": "regex", "pattern": r"[a-z]+@[a-z]+\.test", "replace": "[EMAIL]"}
NER = {"id": "ner", "type": "entity", "labels": ["PERSON", "ORG"], "replace": "[{label}]"}


def expected_hash(value: str) -> str:
    return hmac.new(KEY.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


@pytest.mark.parametrize(
    "spelling",
    ["zyxwq plonk", "Zyxwq_Plonk", "ZYXWQ-PLONK", "zyxwq.plonk", "zYxWq Plonk"],
)
def test_literal_matches_case_and_separator_variants(spelling: str) -> None:
    text, found = sanitize_text(f"trip {spelling} 01", FILENAME, make_rules(WHO))
    assert text == "trip [PERSON] 01"
    assert found == [Redaction("who", FILENAME, expected_hash(spelling), "[PERSON]")]


def test_literal_separator_is_one_for_one() -> None:
    text, found = sanitize_text("zyxwq__plonk", FILENAME, make_rules(WHO))
    assert text == "zyxwq__plonk" and found == []


def test_literal_has_no_word_boundary() -> None:
    text, _ = sanitize_text("xxzyxwq_plonk2020", FILENAME, make_rules(WHO))
    assert text == "xx[PERSON]2020"


def test_longest_literal_wins() -> None:
    short = {"id": "first", "type": "literal", "values": ["zyxwq"], "replace": "[FIRST]"}
    text, found = sanitize_text("zyxwq plonk and zyxwq", FILENAME, make_rules(short, WHO))
    assert text == "[PERSON] and [FIRST]"
    assert [r.rule_id for r in found] == ["who", "first"]


def test_one_redaction_per_match() -> None:
    text, found = sanitize_text("zyxwq-plonk, Zyxwq.Plonk", FILENAME, make_rules(WHO))
    assert text == "[PERSON], [PERSON]"
    assert [r.before_hash for r in found] == [
        expected_hash("zyxwq-plonk"),
        expected_hash("Zyxwq.Plonk"),
    ]


def test_literal_replacement_is_not_matched_again() -> None:
    echo = {"id": "echo", "type": "literal", "values": ["person"], "replace": "[PERSON]"}
    text, found = sanitize_text("zyxwq plonk", FILENAME, make_rules(WHO, echo))
    assert text == "[PERSON]" and len(found) == 1


def test_regex_runs_after_literals() -> None:
    # The literal removes the name first, so the regex sees only what is left.
    mail = {**MAIL, "pattern": r"[a-z ]+@[a-z]+\.test"}
    text, found = sanitize_text("zyxwq plonk@host.test", FILENAME, make_rules(mail, WHO))
    assert text == "[PERSON]@host.test"
    assert [r.rule_id for r in found] == ["who"]


def test_regex_replacement_is_literal() -> None:
    rule = {"id": "num", "type": "regex", "pattern": r"(\d+)", "replace": r"[\1]"}
    text, _ = sanitize_text("a 42 b", FILENAME, make_rules(rule))
    assert text == r"a [\1] b"


def test_regex_empty_match_redacts_nothing() -> None:
    rule = {"id": "maybe", "type": "regex", "pattern": r"\d*", "replace": "[N]"}
    text, found = sanitize_text("ab7c", FILENAME, make_rules(rule))
    assert text == "ab[N]c"
    assert [r.before_hash for r in found] == [expected_hash("7")]


def test_entity_sees_text_after_literal_and_regex() -> None:
    seen: list[tuple[str, list[str]]] = []

    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        seen.append((text, list(labels)))
        return [("Qorvath Ltd", "ORG")]

    text, found = sanitize_text(
        "zyxwq plonk joe@host.test Qorvath Ltd", FILENAME, make_rules(NER, MAIL, WHO), entity
    )
    assert seen == [("[PERSON] [EMAIL] Qorvath Ltd", ["PERSON", "ORG"])]
    assert text == "[PERSON] [EMAIL] [ORG]"
    assert [r.rule_id for r in found] == ["who", "mail", "ner"]
    assert found[-1] == Redaction("ner", FILENAME, expected_hash("Qorvath Ltd"), "[ORG]")


def test_entity_drops_absent_spans_and_unasked_labels() -> None:
    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [("Nowhere Inc", "ORG"), ("Velmora", "LOCATION"), ("Drax", "PERSON")]

    text, found = sanitize_text("Velmora with Drax", FILENAME, make_rules(NER), entity)
    assert text == "Velmora with [PERSON]"
    assert len(found) == 1


def test_entity_longer_span_first() -> None:
    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [("Drax", "PERSON"), ("Drax Holdings", "ORG")]

    text, found = sanitize_text("Drax Holdings, Drax", FILENAME, make_rules(NER), entity)
    assert text == "[ORG], [PERSON]"
    assert [r.after_value for r in found] == ["[ORG]", "[PERSON]"]


def test_entity_rule_is_skipped_without_a_callable() -> None:
    text, found = sanitize_text("Drax", FILENAME, make_rules(NER))
    assert text == "Drax" and found == []


def test_redactions_never_hold_the_value() -> None:
    _, found = sanitize_text("zyxwq plonk", FILENAME, make_rules(WHO))
    assert "zyxwq" not in repr(found).lower()
    assert len(found[0].before_hash) == 64


def test_hash_depends_on_the_key() -> None:
    other = make_rules(WHO, key="ffeeddccbbaa99887766554433221100")
    _, mine = sanitize_text("zyxwq plonk", FILENAME, make_rules(WHO))
    _, theirs = sanitize_text("zyxwq plonk", FILENAME, other)
    assert mine[0].before_hash != theirs[0].before_hash


def test_exif_field_rules_do_not_touch_text() -> None:
    gps = {"id": "gps", "type": "exif_field", "fields": ["GPSLatitude"]}
    assert sanitize_text("GPSLatitude", FILENAME, make_rules(gps)) == ("GPSLatitude", [])


def test_sanitize_name_redacts_segments_and_stem_not_the_extension() -> None:
    ext = {"id": "ext", "type": "literal", "values": ["jpg"], "replace": "[X]"}
    name = sanitize_name("zyxwq_plonk/2020 jpg/zyxwq.plonk.jpg", make_rules(WHO, ext))
    assert name.segments == ("[PERSON]", "2020 [X]")
    assert name.stem == "[PERSON]"
    assert name.suffix == ".jpg"
    assert [(r.rule_id, r.field) for r in name.redactions] == [
        ("who", PATH_SEGMENT),
        ("ext", PATH_SEGMENT),
        ("who", FILENAME),
    ]


def test_sanitize_name_file_at_the_root() -> None:
    name = sanitize_name("Zyxwq-Plonk.png", make_rules(WHO))
    assert (name.segments, name.stem, name.suffix) == ((), "[PERSON]", ".png")


@pytest.mark.parametrize("bad", ["/source/a.jpg", "../a.jpg", "", "a/../b.jpg"])
def test_sanitize_name_needs_a_relative_path(bad: str) -> None:
    with pytest.raises(ValueError, match="relative to source_root"):
        sanitize_name(bad, make_rules(WHO))


def test_sanitize_name_keeps_only_an_image_extension_out_of_the_rules() -> None:
    upper = sanitize_name("Zyxwq Plonk.JPG", make_rules(WHO))
    assert (upper.stem, upper.suffix) == ("[PERSON]", ".JPG")
    # Not an image extension: the dotted tail is part of the name and is redacted.
    tail = sanitize_name("zyxwq.plonk", make_rules(WHO))
    assert (tail.stem, tail.suffix) == ("[PERSON]", "")


# --- PR #65 round 3: repr of results, surrogates, rule ids ------------------------------


def test_redaction_and_sanitized_name_repr_hide_names_and_replacements() -> None:
    leaky = {**WHO, "replace": "[Qwvplk]"}  # a name written as the replacement
    name = sanitize_name("Mordelk/zyxwq plonk Vantrim.jpg", make_rules(leaky))
    assert name.stem == "[Qwvplk] Vantrim"  # residue that no rule matched
    _, found = sanitize_text("zyxwq plonk", FILENAME, make_rules(leaky))
    shown = [repr(name), str(name), repr(name.redactions), repr(found), str(found[0])]
    for text in shown:
        for secret in ("Qwvplk", "Vantrim", "Mordelk", "zyxwq", "Zyxwq"):
            assert secret not in text, text
    assert repr(name) == "SanitizedName(suffix='.jpg')"
    assert found[0].after_value == "[Qwvplk]"  # still stored, never printed


def surrogate_hash(value: str) -> str:
    data = value.encode("utf-8", "surrogatepass")
    return hmac.new(KEY.encode("utf-8"), data, hashlib.sha256).hexdigest()


def test_hashed_value_may_hold_a_lone_surrogate() -> None:
    value = "Drax\udcff"  # a byte decoded with surrogateescape

    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [(value, "PERSON")]

    text, found = sanitize_text(f"by {value}", FILENAME, make_rules(NER), entity)
    assert text == "by [PERSON]"
    assert found[0].before_hash == surrogate_hash(value)
    assert before_hash("Zyxwq\ud800", KEY.encode("utf-8")) == surrogate_hash("Zyxwq\ud800")


def test_log_key_with_a_lone_surrogate_is_refused_unchained(tmp_path: Path) -> None:
    bad = {LOG_KEY_ENV: "Zyxwq\udcffPlonk"}
    with pytest.raises(SanitizeConfigError) as info:
        log_key(bad)
    message = str(info.value)
    assert LOG_KEY_ENV in message and "make init" in message
    assert "Zyxwq" not in message and "udcff" not in message and "\udcff" not in message
    assert_unchained(info.value)
    load_error(tmp_path, rules_data(), env=bad)


@pytest.mark.parametrize(
    "bad",
    ["Zyxwq", "zyxwq plonk", "-zyxwq", "zyxwq.plonk", "z" * 65, ""],
    ids=["upper", "space", "leading-dash", "dot", "too-long", "empty"],  # tmp_path takes the id
)
def test_rule_id_is_a_label(tmp_path: Path, bad: str) -> None:
    data = rules_data()
    data["rules"][0]["id"] = bad
    assert "rules[0].id: string_pattern_mismatch" in load_error(tmp_path, data)
