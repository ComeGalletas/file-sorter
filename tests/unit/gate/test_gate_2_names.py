"""TST-005.2.1: gate 2's seed draw, residual matcher and names judge (TST-005.D2, D4, D8).

Synthetic rules and a fake entity detector only: no sanitize.yaml, no Ollama.
"""

import importlib.util
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pytest

from classifier.sanitize.rules import (
    LOG_KEY_ENV,
    EntityRule,
    ExifSettings,
    LiteralRule,
    RegexRule,
    Rules,
    log_key,
    sanitize_name,
)

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_2.py"
spec = importlib.util.spec_from_file_location("gate_2", SCRIPT)
assert spec and spec.loader
gate_2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_2)

KEY = log_key({LOG_KEY_ENV: "00112233445566778899aabbccddeeff"})
SECRET = "Zyxwq Plonk"  # stands in for the human's value: must never surface

# Invented for this test (not the eval file), in entity_synthetic.yaml's shape.
NAMES_DATA = {
    "people": {
        "first": ["Quorbel", "Ystrava", "Plimmo", "Ox"],
        "last": ["Vantrex", "Odderwick", "Snarr"],
    },
    "orgs": ["Glimfold Works", "Tarrowby Club"],
    "places": ["Murrowfen Bay", "Ostrivel"],
    "separators": ["_", "-", " ", ".", ""],
}
NAMES = gate_2.entity_names(NAMES_DATA)

EMAIL = RegexRule(id="email", type="regex", pattern=r"[\w.+-]+@[\w-]+\.[\w.]+", replace="[EMAIL]")
PHONE = RegexRule(id="phone", type="regex", pattern=r"\+?\d[\d\s().-]{7,}\d", replace="[PHONE]")
ENTITIES = EntityRule(
    id="entities", type="entity", labels=["PERSON", "ORG", "LOCATION"], replace="[{label}]"
)


def rules(*extra: object, pool: Sequence[str] = (SECRET,)) -> Rules:
    literal = LiteralRule(id="mine", type="literal", values=list(pool), replace="[PERSON]")
    return Rules(
        exif=ExifSettings(mode="strip_all"),
        rules=(literal, *extra),  # type: ignore[arg-type]
        log_key=KEY,
    )


def fake_entity(seeds: Sequence[object]):
    """Finds exactly the seeded fictional names, as a perfect detector would."""
    known = [(s.value, s.label) for s in seeds if s.source == gate_2.ENTITY]

    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [(span, label) for span, label in known if span in text and label in labels]

    return entity


def sanitized_texts(seeds, rule_set: Rules, entity=None) -> list[str]:
    out = []
    for seed in seeds:
        name = sanitize_name(seed.path, rule_set, entity)
        out.append("/".join((*name.segments, name.stem)))
    return out


def residues(rule_set: Rules, entity_on: bool = True) -> list[bool]:
    seeds = gate_2.draw_seeds(gate_2.literal_values(rule_set.rules), NAMES)
    texts = sanitized_texts(seeds, rule_set, fake_entity(seeds) if entity_on else None)
    tokens = gate_2.replacement_tokens(rule_set.rules)
    return [gate_2.has_residue(s, t, tokens) for s, t in zip(seeds, texts, strict=True)]


# --- the draw --------------------------------------------------------------------------


def test_the_draw_is_pinned_and_has_the_fixed_shares() -> None:
    first = gate_2.draw_seeds([SECRET], NAMES)
    assert first == gate_2.draw_seeds([SECRET], NAMES)
    assert len(first) == gate_2.TOTAL_SEEDS == 50
    assert Counter(s.source for s in first) == {"literal": 20, "contact": 10, "entity": 20}
    assert Counter(s.label for s in first if s.source == "entity") == {
        "PERSON": 10,
        "ORG": 5,
        "LOCATION": 5,
    }


def test_a_different_seed_draws_differently() -> None:
    assert gate_2.draw_seeds([SECRET], NAMES, 1) != gate_2.draw_seeds([SECRET], NAMES, 2)


def test_the_draw_looks_the_same_whatever_the_pool_holds() -> None:
    """TST-005.D4: shares, shapes and every non-literal seed are independent of the pool."""
    small = gate_2.draw_seeds(["Aaaa Bbbb"], NAMES)
    large = gate_2.draw_seeds([f"Cccc{i} Dddd" for i in range(10)], NAMES)
    assert [s.source for s in small] == [s.source for s in large]
    assert small[20:] == large[20:]
    for a, b in zip(small[:20], large[:20], strict=True):
        assert a.path.replace(a.value, "<v>") == b.path.replace(b.value, "<v>")


def test_literals_are_drawn_with_replacement_from_a_one_value_pool() -> None:
    seeds = gate_2.draw_seeds([SECRET], NAMES)[:20]
    assert all(s.source == "literal" for s in seeds)
    assert {s.value.casefold().replace("_", " ").replace("-", " ").replace(".", " ")
            for s in seeds} == {SECRET.casefold()}  # fmt: skip


def test_literal_spellings_vary_separator_case_and_place() -> None:
    seeds = gate_2.draw_seeds([SECRET], NAMES)[:20]
    separators = {sep for s in seeds for sep in " _-." if sep in s.value}
    assert len(separators) >= 3
    assert len({s.value for s in seeds}) >= 4  # case variants too
    folders = [s for s in seeds if "/" in s.path]
    assert len(folders) == 5 and all(s.value in s.path.split("/")[0] for s in folders)
    assert all(s.path.endswith(".jpg") for s in seeds)


def test_a_case_change_that_alters_the_letters_is_not_used() -> None:
    seeds = gate_2.draw_seeds(["Straße Weiß"], NAMES)[:20]
    for seed in seeds:
        assert len(seed.value) == len("Straße Weiß")
        assert "SS" not in seed.value


def test_person_seeds_carry_their_name_words_of_three_letters_or_more() -> None:
    people = [s for s in gate_2.draw_seeds([SECRET], NAMES) if s.label == "PERSON"]
    assert people and all(1 <= len(s.words) <= 2 for s in people)
    assert all("Ox" not in s.words for s in people)
    assert all(not s.words for s in gate_2.draw_seeds([SECRET], NAMES) if s.label != "PERSON")


def test_an_empty_literal_pool_fails_naming_the_file_and_the_rule_type() -> None:
    with pytest.raises(gate_2.GateSetupError, match=r"sanitize\.yaml has no `literal` rule"):
        gate_2.draw_seeds([], NAMES)


@pytest.mark.parametrize(
    "broken",
    [
        None,
        [],
        {"people": {"first": ["A"], "last": ["B"]}, "orgs": ["C"], "places": ["D"]},
        {**NAMES_DATA, "orgs": []},
        {**NAMES_DATA, "places": ["ok", 3]},
    ],
)
def test_a_malformed_entity_file_fails_naming_it(broken: object) -> None:
    with pytest.raises(gate_2.GateSetupError, match="entity_synthetic.yaml"):
        gate_2.entity_names(broken)


def test_literal_values_and_tokens_come_from_the_rules() -> None:
    rule_set = rules(EMAIL, ENTITIES, pool=("one", "two words"))
    assert gate_2.literal_values(rule_set.rules) == ["one", "two words"]
    assert set(gate_2.replacement_tokens(rule_set.rules)) == {
        "[PERSON]",
        "[EMAIL]",
        "[ORG]",
        "[LOCATION]",
    }


# --- the residual matcher ----------------------------------------------------------------


def seed(value: str, label: str = "", words: tuple[str, ...] = ()) -> object:
    source = gate_2.ENTITY if label else gate_2.LITERAL
    return gate_2.Seed(source, value, f"{value}.jpg", label, words)


@pytest.mark.parametrize(
    "text",
    [
        "x zyxwq plonk y",
        "ZYXWQ_PLONK",
        "zyxwq-Plonk_2031",
        "ZyxwqPlonk",
        "a.zyxwq.plonk",
        "f/zyxwq plonk",
    ],
)
def test_the_value_survives_in_any_spelling(text: str) -> None:
    assert gate_2.has_residue(seed(SECRET), text)


@pytest.mark.parametrize("text", ["[PERSON]_2031", "zyxwq", "plonk zyxwq", ""])
def test_a_redacted_or_partial_value_is_no_residue(text: str) -> None:
    assert not gate_2.has_residue(seed(SECRET), text, ("[PERSON]",))


def test_a_value_spelled_like_a_token_is_no_residue() -> None:
    assert gate_2.has_residue(seed("person"), "[PERSON]_2031")
    assert not gate_2.has_residue(seed("person"), "[PERSON]_2031", ("[PERSON]",))


def test_a_person_name_word_is_a_residue() -> None:
    person = seed("Quorbel_Vantrex", "PERSON", ("Quorbel", "Vantrex"))
    assert gate_2.has_residue(person, "[PERSON] vantrex.jpg", ("[PERSON]",))
    assert not gate_2.has_residue(person, "[PERSON] 2031", ("[PERSON]",))


def test_an_org_or_place_word_alone_is_no_residue() -> None:
    """TST-005.D8: orgs and places are checked as the full value only."""
    place = seed("Murrowfen Bay", "LOCATION")
    assert not gate_2.has_residue(place, "Bay trip [LOCATION]", ("[LOCATION]",))
    assert gate_2.has_residue(place, "murrowfen-bay trip", ("[LOCATION]",))


# --- through the real sanitize_name ------------------------------------------------------


def test_every_seed_is_redacted_by_complete_rules() -> None:
    found = residues(rules(EMAIL, PHONE, ENTITIES))
    assert not any(found)
    ok, line = gate_2.judge_names(found)
    assert ok and line == "names: residual seeded values 0.0% (required 0.0%): ok"


def test_a_missing_regex_rule_leaves_contact_residue() -> None:
    found = residues(rules(PHONE, ENTITIES))
    assert all(found[20:25]) and not any(found[:20]) and not any(found[25:])
    assert gate_2.judge_names(found) == (
        False,
        "names: residual seeded values 10.0% (required 0.0%): FAIL",
    )


def test_no_entity_detector_leaves_entity_residue() -> None:
    found = residues(rules(EMAIL, PHONE, ENTITIES), entity_on=False)
    assert all(found[30:]) and not any(found[:30])
    assert gate_2.judge_names(found) == (
        False,
        "names: residual seeded values 40.0% (required 0.0%): FAIL",
    )


def test_one_residue_rounds_up_and_a_short_draw_fails() -> None:
    assert gate_2.judge_names([True] + [False] * 49)[1].startswith(
        "names: residual seeded values 2.0%"
    )
    assert gate_2._pct_up(1, 1000) == "0.1%"
    assert gate_2._pct_down(999, 1000) == "99.9%"
    assert gate_2.judge_names([False] * 49) == (
        False,
        "names: the draw did not make 50 seeds: FAIL",
    )


def test_the_human_value_never_surfaces() -> None:
    rule_set = rules(EMAIL, PHONE, ENTITIES, pool=(SECRET, "Second Secretvalue"))
    seeds = gate_2.draw_seeds(gate_2.literal_values(rule_set.rules), NAMES)
    found = residues(rule_set)
    shown = " ".join([repr(seeds), *map(repr, seeds), *gate_2.judge_names(found)[1:]])
    shown += " ".join(gate_2.judge_names([True] * 50)[1:])
    for planted in (SECRET, "Second Secretvalue"):
        for part in planted.split():
            assert not re.search(re.escape(part), shown, re.IGNORECASE)
