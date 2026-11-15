"""NAME-001.1: the template engine (R-NAME-1, R-NAME-2, R-NAME-3, R-NAME-5, R-NAME-7, R-NAME-8,
R-SAN-7).

Synthetic coinages only (privacy item 8). Nothing here reads a file or calls a model.
"""

from datetime import datetime

import pytest

from classifier.naming.templates import (
    BUILTINS,
    MAX_TEMPLATE_LEN,
    Field,
    Filter,
    Ref,
    TemplateError,
    Tokens,
    parse,
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
