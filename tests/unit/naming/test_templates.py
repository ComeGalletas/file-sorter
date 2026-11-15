"""NAME-001.1: the template engine (R-NAME-1, R-NAME-2, R-NAME-3, R-NAME-5, R-NAME-7, R-NAME-8,
R-SAN-7).

Synthetic coinages only (privacy item 8). Nothing here reads a file or calls a model.
"""

import logging
from datetime import datetime

import pytest

from classifier.config import NamingConfig
from classifier.naming.templates import (
    BUILTINS,
    MAX_TEMPLATE_LEN,
    Field,
    Filter,
    Ref,
    TemplateError,
    Tokens,
    normalize,
    parse,
    render,
)

# --- parse --------------------------------------------------------------------------------


def test_parse_splits_literals_and_fields() -> None:
    parsed = parse("x_{subject|title|max=5}_{seq:3}")
    assert parsed.parts == (
        "x_",
        Field(Ref("subject"), (Filter("title"), Filter("max", 5))),
        "_",
        Field(Ref("seq", 3)),
    )


def test_or_takes_a_token_fallback() -> None:
    # NAME-001.D2: `|or=` takes a token as its fallback.
    parsed = parse("{reference|or={subject}}")
    assert parsed.parts == (Field(Ref("reference"), (Filter("or", Ref("subject")),)),)


def test_or_takes_a_literal_fallback() -> None:
    parsed = parse("{topic|or=general}")
    assert parsed.parts == (Field(Ref("topic"), (Filter("or", "general"),)),)


def test_every_builtin_parses() -> None:
    assert set(BUILTINS) == {
        "descriptive",
        "reference",
        "dated",
        "category-seq",
        "keep-original",
        "hash",
    }
    for template in BUILTINS.values():
        parse(template)


def test_builtins_match_the_decisions() -> None:
    # NAME-001.D1 and NAME-001.D2, exactly.
    assert BUILTINS["descriptive"] == "{subject}_{detail|max=40}_{seq:3}"
    assert BUILTINS["reference"] == "{reference|or={subject}}_{seq:3}"
    assert BUILTINS["dated"] == "{date}_{subject}_{seq:3}"
    assert BUILTINS["category-seq"] == "{category}_{seq:4}"
    assert BUILTINS["keep-original"] == "{original_sanitized}"
    assert BUILTINS["hash"] == "{short_hash}"


def test_builtins_that_use_reference_declare_a_fallback() -> None:
    # R-NAME-7: until M6, a built-in using {reference} must declare an `|or=` fallback.
    for template in BUILTINS.values():
        for part in parse(template).parts:
            if isinstance(part, Field) and part.ref.name == "reference":
                assert any(f.kind == "or" for f in part.filters)


@pytest.mark.parametrize(
    ("template", "has_seq"),
    [
        ("{subject}_{seq}", True),
        ("{subject}_{seq:4}", True),
        ("{reference|or={seq}}", True),
        ("{subject}", False),
        ("{short_hash}", False),
    ],
)
def test_has_seq(template: str, has_seq: bool) -> None:
    assert parse(template).has_seq is has_seq


QORVEX = "Qorvex"  # a coined string planted in bad templates

BAD_TEMPLATES = [
    pytest.param("", id="empty"),
    pytest.param("x" * (MAX_TEMPLATE_LEN - 9) + "{subject}x", id="too-long"),
    pytest.param("{subject}\n" + QORVEX, id="two-lines"),
    pytest.param("{subject}\r" + QORVEX, id="carriage-return"),
    pytest.param(QORVEX, id="no-token"),
    pytest.param("{" + QORVEX.lower() + "}", id="unknown-token"),
    pytest.param("{subject|" + QORVEX.lower() + "}", id="unknown-filter"),
    pytest.param("{subject:3}_" + QORVEX, id="width-on-non-seq"),
    pytest.param("{seq:0}_" + QORVEX, id="zero-width"),
    pytest.param("{seq:x}_" + QORVEX, id="bad-width"),
    pytest.param("{subject|max=0}_" + QORVEX, id="max-zero"),
    pytest.param("{subject|max}_" + QORVEX, id="max-no-value"),
    pytest.param("{subject|or=}_" + QORVEX, id="or-empty"),
    pytest.param("{subject|or={" + QORVEX.lower() + "}}", id="or-unknown-token"),
    pytest.param("{subject|or={detail}_" + QORVEX, id="or-unclosed"),
    pytest.param("{subject_" + QORVEX, id="unclosed"),
    pytest.param(QORVEX + "}{subject}", id="stray-close"),
    pytest.param("{{subject}}_" + QORVEX, id="double-brace"),
    pytest.param("{Subject}_" + QORVEX, id="uppercase-token"),
]


@pytest.mark.parametrize("template", BAD_TEMPLATES)
def test_bad_templates_raise_fixed_text_unchained(template: str) -> None:
    with pytest.raises(TemplateError) as caught:
        parse(template)
    error = caught.value
    assert error.__cause__ is None
    assert error.__context__ is None
    # The template text is never echoed (privacy item 19).
    assert QORVEX not in str(error) and QORVEX.lower() not in str(error)
    assert "{" not in str(error) and "}" not in str(error)
    if template:
        assert template not in str(error)
    assert QORVEX not in repr(error)


def test_template_at_the_length_limit_parses() -> None:
    template = "x" * (MAX_TEMPLATE_LEN - len("{subject}")) + "{subject}"
    assert len(template) == MAX_TEMPLATE_LEN
    parse(template)


# --- Tokens -------------------------------------------------------------------------------

PLANTS = {
    "subject": "Zhyndelsubj",
    "detail": "Qorvexdetail",
    "caption": "Vrolmacaption",
    "reference": "Thexilref",
    "format": "Plorbformat",
    "topic": "Wuxtopic",
    "original_sanitized": "Kranzoriginal",
    "ext": "Zubext",
}
TAG_PLANT = "Glimtag"
DATE_PLANT = datetime(1903, 7, 11, 13, 57, 29)


def test_tokens_repr_hides_text_and_dates() -> None:
    tokens = Tokens(
        short_hash="0badc0de",
        branch="nsfw",
        animated=True,
        seq=7,
        tags=(TAG_PLANT,),
        taken_at=DATE_PLANT,
        mtime=DATE_PLANT,
        **PLANTS,
    )
    # Prove each plant is held before asserting its absence.
    for name, value in PLANTS.items():
        assert getattr(tokens, name) == value
    assert tokens.tags == (TAG_PLANT,)
    assert tokens.taken_at == DATE_PLANT and tokens.mtime == DATE_PLANT

    for text in (repr(tokens), str(tokens)):
        for value in (*PLANTS.values(), TAG_PLANT):
            assert value not in text
        assert "1903" not in text and "13, 57" not in text
        assert "0badc0de" in text  # the hash is what logs carry


# --- render -------------------------------------------------------------------------------

WHEN_EXIF = datetime(2031, 4, 5, 6, 7, 8)
WHEN_MTIME = datetime(2032, 9, 10, 11, 12, 13)


def naming(**overrides: object) -> NamingConfig:
    values: dict[str, object] = {
        "default_template": "descriptive",
        "nsfw_template": None,
        "nsfw_prefix": "nsfw_",
        "max_len": 120,
    }
    values.update(overrides)
    return NamingConfig(**values)


def keep(text: str) -> str:
    return text


def tokens(**overrides: object) -> Tokens:
    values: dict[str, object] = {
        "short_hash": "0badc0de",
        "subject": "Zhyndel Vorp",
        "detail": "a plimmer beside the krandle",
        "caption": "Zhyndel stands near a quarbish.",
        "tags": ("plimmer", "krandle"),
        "format": "Glorpic",
        "topic": "Vexmoor",
        "original_sanitized": "qorvex holiday 0042",
        "ext": ".png",
        "mtime": WHEN_MTIME,
    }
    values.update(overrides)
    return Tokens(**values)  # type: ignore[arg-type]


def go(template: str, row: Tokens | None = None, **config: object) -> str:
    return render(template, row or tokens(), config=naming(**config), sanitize=keep)


def test_descriptive() -> None:
    assert go(BUILTINS["descriptive"]) == "zhyndel_vorp_a_plimmer_beside_the_krandle_001"


def test_descriptive_caps_detail_at_40() -> None:
    row = tokens(detail="x" * 39 + "yz", seq=12)
    assert go(BUILTINS["descriptive"], row) == "zhyndel_vorp_" + "x" * 39 + "y_012"


def test_reference_falls_back_to_subject_while_empty() -> None:
    # NAME-001.D2 / R-NAME-7: {reference} is empty until M6, so `|or={subject}` renders.
    assert go(BUILTINS["reference"], tokens(seq=3)) == "zhyndel_vorp_003"


def test_reference_used_when_set() -> None:
    assert go(BUILTINS["reference"], tokens(reference="Thexil Saga")) == "thexil_saga_001"


def test_or_falls_back_on_whitespace_only() -> None:
    assert go("{reference|or={subject}}", tokens(reference="  ")) == "zhyndel_vorp"


def test_or_literal_fallback() -> None:
    assert go("{topic|or=general}_{seq}", tokens(topic=None)) == "general_1"


def test_or_token_fallback_keeps_its_width() -> None:
    assert go("{reference|or={seq:3}}", tokens(seq=4)) == "004"


def test_dated_prefers_the_kept_exif_date() -> None:
    # R-NAME-3
    row = tokens(taken_at=WHEN_EXIF)
    assert go(BUILTINS["dated"], row) == "2031_04_05_zhyndel_vorp_001"


def test_dated_falls_back_to_mtime() -> None:
    assert go(BUILTINS["dated"]) == "2032_09_10_zhyndel_vorp_001"


def test_time_and_year() -> None:
    row = tokens(taken_at=WHEN_EXIF)
    assert go("{year}_{time}", row) == "2031_060708"


def test_no_date_renders_empty() -> None:
    assert go("{date}_{subject}", tokens(mtime=None)) == "zhyndel_vorp"


def test_category_seq_with_topic() -> None:
    assert go(BUILTINS["category-seq"], tokens(seq=5)) == "vexmoor_glorpic_0005"


def test_category_without_topic_is_the_format() -> None:
    assert go("{category}", tokens(topic=None)) == "glorpic"


def test_keep_original_and_hash() -> None:
    assert go(BUILTINS["keep-original"]) == "qorvex_holiday_0042"
    assert go(BUILTINS["hash"]) == "0badc0de"


def test_animated_renders_word_or_nothing() -> None:
    assert go("{subject}_{animated}", tokens(animated=True)) == "zhyndel_vorp_animated"
    assert go("{subject}_{animated}", tokens(animated=False)) == "zhyndel_vorp"


def test_remaining_tokens() -> None:
    row = tokens(branch="safe")
    assert go("{caption}", row) == "zhyndel_stands_near_a_quarbish"
    assert go("{tags}", row) == "plimmer_krandle"
    assert go("{format}_{topic}_{branch}_{ext}", row) == "glorpic_vexmoor_safe_png"
    assert go("{short_hash}_{seq}", tokens(seq=27)) == "0badc0de_27"


def test_filters_apply_left_to_right() -> None:
    row = tokens(reference="")
    assert go("{reference|max=3|or=plonk}", row) == "plonk"
    assert go("{subject|max=3|title}", row) == "zhy"
    assert go("{subject|title}", row) == "zhyndel_vorp"  # normalization lowercases it


@pytest.mark.parametrize(
    ("subject", "stem"),
    [
        ("Zhýndél", "zhyndel"),  # ASCII-fold
        ("Qor!!vex  --  Plim", "qor_vex_plim"),  # symbols and repeats collapse
        ("__Qorvex__", "qorvex"),  # no edge underscores
        ("Qor\udcffvex", "qorvex"),  # a lone surrogate is dropped, not quoted
        ("ＱＯＲＶＥＸ", "qorvex"),  # NFKD compatibility forms
    ],
)
def test_normalization(subject: str, stem: str) -> None:
    assert normalize(subject) == stem
    assert go("{subject}", tokens(subject=subject)) == stem


def test_sanitize_sees_the_normalized_stem_and_is_renormalized() -> None:
    # R-SAN-7: the rendered name is re-run through the rules; a replacement such as
    # "[REDACTED]" is normalized again.
    seen: list[str] = []

    def rules(text: str) -> str:
        seen.append(text)
        return text.replace("qorvex", "[REDACTED]")

    row = tokens(original_sanitized="Qorvex Plim")
    out = render(BUILTINS["keep-original"], row, config=naming(), sanitize=rules)
    assert seen == ["qorvex_plim"]
    assert out == "redacted_plim"


def test_empty_stem_falls_back_to_short_hash() -> None:
    # NAME-001.D4
    def wipe(text: str) -> str:
        return ""

    row = tokens(original_sanitized="Qorvex")
    assert render("{original_sanitized}", row, config=naming(), sanitize=wipe) == "0badc0de"
    adult = tokens(original_sanitized="Qorvex", branch="nsfw")
    out = render("{original_sanitized}", adult, config=naming(), sanitize=wipe)
    assert out == "nsfw_0badc0de"


def test_empty_render_falls_back_to_short_hash() -> None:
    assert go("{reference}", tokens(reference="")) == "0badc0de"


def test_prefix_only_on_adult_rows() -> None:
    # R-NAME-8
    assert go("{subject}", tokens(branch="nsfw")) == "nsfw_zhyndel_vorp"
    assert go("{subject}", tokens(branch="safe")) == "zhyndel_vorp"


def test_empty_prefix_disables_it() -> None:
    assert go("{subject}", tokens(branch="nsfw"), nsfw_prefix="") == "zhyndel_vorp"


def test_prefix_counts_toward_the_cap() -> None:
    row = tokens(branch="nsfw", subject="q" * 200)
    out = go("{subject}", row, max_len=120)
    assert len(out) == 120
    assert out == "nsfw_" + "q" * 115


def test_default_cap_is_120() -> None:
    assert len(go("{subject}", tokens(subject="q" * 300))) == 120


def test_cap_that_cuts_seq_keeps_the_head() -> None:
    # NAME-001.D5: the cap keeps the head, so a long name can lose its trailing {seq};
    # NAME-001.2's unique() still guarantees no overwrite. No trailing "_" survives the cut.
    row = tokens(subject="plimmerkrandle", detail="quarbish", seq=7)
    out = go(BUILTINS["descriptive"], row, max_len=24)
    assert out == "plimmerkrandle_quarbish"  # "_007" cut, and the dangling "_" stripped
    assert "007" not in out


def test_render_accepts_a_parsed_template() -> None:
    assert go("{subject}") == render(parse("{subject}"), tokens(), config=naming(), sanitize=keep)


def test_render_rejects_a_bad_template_unchained() -> None:
    with pytest.raises(TemplateError) as caught:
        go("{qorvex}")
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "qorvex" not in str(caught.value)


def test_render_prints_and_logs_nothing(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    out = go(BUILTINS["descriptive"], tokens(branch="nsfw"))
    assert out.startswith("nsfw_zhyndel")  # the name was made...
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""  # ...and nothing printed it
    assert caplog.records == []
