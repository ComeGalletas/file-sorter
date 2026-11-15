"""TST-016.1: gate 5's draw, residue matcher, judges and verdict (TST-016.D1, D3, D5).

Synthetic rules, coined values and a fake entity detector only: no sanitize.yaml, no Ollama,
no db. The pipeline below (sanitize the path, sanitize the caption on write, render through
the real templates) is a stand-in for the caption and name nodes, which the runner drives at
`make gate-5` (TST-016.1.3).
"""

import builtins
import dataclasses
import importlib.util
import os
import re
import uuid
from collections import Counter
from collections.abc import Callable, Sequence
from pathlib import Path

import pytest

from classifier.config import NamingConfig
from classifier.naming.templates import BUILTINS, Tokens, parse, render
from classifier.sanitize.rules import (
    FILENAME,
    LOG_KEY_ENV,
    EntityRule,
    ExifSettings,
    LiteralRule,
    RegexRule,
    Rules,
    load_rules,
    log_key,
    sanitize_name,
    sanitize_text,
)

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "gate_5.py"
_spec = importlib.util.spec_from_file_location("gate_5_checks", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_5 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_5)

KEY_HEX = "00112233445566778899aabbccddeeff"
KEY = log_key({LOG_KEY_ENV: KEY_HEX})
SECRET = "Zyxwq Plonkravel"  # stands in for the human's value: must never surface

# Invented for this test, in entity_synthetic.yaml's shape (no word of FILLER inside).
NAMES = gate_5.entity_names(
    {
        "people": {"first": ["Quorbel", "Ystrava", "Ox"], "last": ["Vantrex", "Odderwick"]},
        "orgs": ["Glimfold Works", "Tarrowby Club"],
        "places": ["Murrowfen Bay", "Ostrivel"],
        "separators": ["_", "-", " ", ".", ""],
    }
)
NAMING = NamingConfig(
    default_template="descriptive", nsfw_template=None, nsfw_prefix="nsfw_", max_len=120
)

EMAIL = RegexRule(id="email", type="regex", pattern=r"[\w.+-]+@[\w-]+\.[\w.]+", replace="[EMAIL]")
PHONE = RegexRule(id="phone", type="regex", pattern=r"\+?\d[\d\s().-]{7,}\d", replace="[PHONE]")
ENTITIES = EntityRule(
    id="entities", type="entity", labels=["PERSON", "ORG", "LOCATION"], replace="[{label}]"
)


def make_rules(pool: Sequence[str] = (SECRET,)) -> Rules:
    literal = LiteralRule(id="mine", type="literal", values=list(pool), replace="[PERSON]")
    return Rules(
        exif=ExifSettings(mode="strip_all"),
        rules=(literal, EMAIL, PHONE, ENTITIES),
        log_key=KEY,
    )


def draw(pool: Sequence[str] = (SECRET,)) -> tuple:
    return gate_5.draw_rows(list(pool), NAMES)


def fake_entity(rows: Sequence) -> Callable[[str, Sequence[str]], list[tuple[str, str]]]:
    """Finds exactly the seeded fictional names, as a perfect detector would."""
    known = {(s.value, s.label) for row in rows for s in row.seeds if s.kind == gate_5.ENTITY}

    def entity(text: str, labels: Sequence[str]) -> list[tuple[str, str]]:
        return [(span, label) for span, label in known if span in text and label in labels]

    return entity


def stand_in_names(rows: Sequence, rules: Rules, *, leak: bool = False) -> list[str]:
    """What the ingest, caption and name nodes do to each row, on the real engine.

    `leak=True` skips every sanitize step: the gate must then find residues.
    """
    entity = fake_entity(rows)
    templates = {**BUILTINS, **gate_5.GATE_TEMPLATES}

    def clean(text: str) -> str:
        return text if leak else sanitize_text(text, FILENAME, rules, entity)[0]

    names = []
    for row in rows:
        if leak:
            original = Path(row.path).stem
        else:
            original = sanitize_name(row.path, rules, entity).stem
        tokens = Tokens(
            short_hash=row.short_hash,
            branch=row.branch,
            seq=row.index + 1,
            subject=clean(row.caption.subject),
            detail=clean(row.caption.detail),
            caption=clean(row.caption.caption),
            tags=tuple(clean(tag) for tag in row.caption.tags),
            format="Photo",
            topic="Qorvexland",
            original_sanitized=original,
            ext="png",
        )
        names.append(render(templates[row.template], tokens, config=NAMING, sanitize=clean))
    return names


def all_seeds(rows: Sequence) -> list:
    return [seed for row in rows for seed in row.seeds]


# --- the draw ---------------------------------------------------------------------------


def test_the_draw_is_pinned_and_has_the_fixed_shares() -> None:
    rows = draw()
    assert rows == draw()
    assert len(rows) == gate_5.TOTAL_NAMES == 500
    assert len({row.source_hash for row in rows}) == 500
    assert len({row.short_hash for row in rows}) == 500
    for place in ("path", "caption"):
        picked = [s for row in rows for s in row.seeds if (s.place == "path") == (place == "path")]
        assert Counter((s.kind, s.label) for s in picked) == {
            ("literal", ""): 200,
            ("contact", "email"): 50,
            ("contact", "phone"): 50,
            ("entity", "PERSON"): 100,
            ("entity", "ORG"): 50,
            ("entity", "LOCATION"): 50,
        }


def test_every_template_runs_on_both_branches() -> None:
    rows = draw()
    assert set(gate_5.TEMPLATE_NAMES) == {*BUILTINS, *gate_5.GATE_TEMPLATES}
    assert {(row.template, row.branch) for row in rows} == {
        (name, branch) for name in gate_5.TEMPLATE_NAMES for branch in ("safe", "nsfw")
    }
    for name, template in gate_5.GATE_TEMPLATES.items():
        assert re.fullmatch(r"[a-z][a-z0-9-]{0,31}", name)  # DB-009.1's name rule
        assert parse(template).has_seq  # parses, and collisions number it
    for row in rows:
        want = gate_5.TEMPLATE_FIELD.get(row.template)
        if want is not None:
            assert row.seeds[1].place == want


def test_a_different_seed_draws_differently() -> None:
    assert gate_5.draw_rows([SECRET], NAMES, 1) != gate_5.draw_rows([SECRET], NAMES, 2)


def test_the_draw_looks_the_same_whatever_the_pool_holds() -> None:
    """TST-005.D4: shapes, templates and every non-literal seed are independent of the pool."""
    small, large = draw(["Aaaqz Bbbqz"]), draw([f"Cccqz{i} Dddqz" for i in range(10)])
    for a, b in zip(small, large, strict=True):
        assert (a.template, a.branch, a.source_hash) == (b.template, b.branch, b.source_hash)
        for sa, sb in zip(a.seeds, b.seeds, strict=True):
            assert (sa.kind, sa.label, sa.place) == (sb.kind, sb.label, sb.place)
            if sa.kind != "literal":
                assert sa == sb


def test_an_empty_literal_pool_fails_with_fixed_text() -> None:
    with pytest.raises(gate_5.GateSetupError) as caught:
        gate_5.draw_rows([], NAMES)
    assert "literal" in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


# --- held before absent -----------------------------------------------------------------


def test_every_seed_is_held_in_its_raw_path_or_caption() -> None:
    rows = draw()
    assert all(gate_5.held(row) for row in rows)
    gate_5.check_held(rows)  # does not raise
    # ...and, where the row's template reads the planted field, the gate's own matcher finds
    # the seed in the raw, unsanitized name.
    names = stand_in_names(rows, make_rules(), leak=True)
    reachable = [s for row in rows for s in row.seeds if reaches(row, s)]
    assert len(reachable) > 300
    assert all(gate_5.residues(reachable, names))


def reaches(row, s) -> bool:
    if s.place == "path":  # the stem only: a folder segment never reaches a name
        return row.template in ("keep-original", "gate-mixed") and "/" not in row.path
    return gate_5.TEMPLATE_FIELD.get(row.template) == s.place


def test_a_seed_that_is_not_held_fails_the_run_with_fixed_text() -> None:
    row = draw()[0]
    lost = dataclasses.replace(row.seeds[0], value="Qzzvorth Nimblequap")
    broken = dataclasses.replace(row, seeds=(lost, row.seeds[1]))
    assert not gate_5.held(broken)
    with pytest.raises(gate_5.GateRunError) as caught:
        gate_5.check_held([broken])
    assert "Qzzvorth" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


# --- the matcher (TST-016.D5) -----------------------------------------------------------


def seed(value: str, words: tuple[str, ...] = ()) -> object:
    return gate_5.Seed("literal", "", "path", value, words)


@pytest.mark.parametrize(
    "name",
    [
        "zyxwq_plonkravel",
        "zyxwqplonkravel_001",  # the separator is gone
        "nsfw_qorvex_zyxwq_plonkravel_007",
        "zyxwq__plonkravel",
    ],
)
def test_the_matcher_finds_a_seed_in_normalized_names(name: str) -> None:
    assert gate_5.residues([seed(SECRET)], [name]) == [True]


def test_the_matcher_folds_accents_and_case() -> None:
    assert gate_5.residues([seed("Žélvorq Ünnath")], ["x_zelvorq_unnath_1"]) == [True]


def test_a_near_miss_is_not_a_residue() -> None:
    assert gate_5.residues([seed(SECRET)], ["zyxwq_plonkrave", "plonkravel_zyxwx"]) == [False]


def test_a_person_word_alone_is_a_residue() -> None:
    person = gate_5.Seed("entity", "PERSON", "subject", "Quorbel Vantrex", ("Quorbel", "Vantrex"))
    assert gate_5.residues([person], ["photo_vantrex_001"]) == [True]


def test_every_seed_is_checked_against_every_name() -> None:
    names = ["qorvex_001", "qorvex_002", "zyxwq_plonkravel_003"]
    assert gate_5.residues([seed(SECRET)], names) == [True]


def test_a_whole_word_replacement_token_is_masked_and_a_glued_one_is_not() -> None:
    spelled_like_token = seed("Person")
    tokens = ("[PERSON]",)
    assert gate_5.residues([spelled_like_token], ["qorvex_person_001"], tokens) == [False]
    assert gate_5.residues([spelled_like_token], ["qorvexpersony_001"], tokens) == [True]


def test_a_value_that_normalizes_to_nothing_cannot_be_in_a_name() -> None:
    assert gate_5.probe_pattern("--- ...") is None
    assert gate_5.residues([seed("--- ...")], ["qorvex_001"]) == [False]


# --- the stand-in pipeline on the real engine -------------------------------------------


def test_sanitized_rows_leave_no_residue_and_the_gate_passes() -> None:
    rules = make_rules()
    rows = draw()
    names = stand_in_names(rows, rules)
    found = gate_5.residues(all_seeds(rows), names, gate_5.replacement_tokens(rules.rules))
    assert not any(found)
    ok, line = gate_5.judge_names(len(names), found)
    assert ok
    assert line == "names: 500 synthetic names, 0 residual seeded values (required 0): ok"


def test_a_leaking_pipeline_fails_the_gate() -> None:
    rules = make_rules()
    rows = draw()
    names = stand_in_names(rows, rules, leak=True)
    found = gate_5.residues(all_seeds(rows), names, gate_5.replacement_tokens(rules.rules))
    ok, line = gate_5.judge_names(len(names), found)
    assert not ok
    assert line == "names: 500 synthetic names, seeded values survived (required 0): FAIL"
    assert SECRET.casefold() not in line.casefold()


def test_one_rule_dropped_is_caught() -> None:
    """The literal rule left out: the human's own values would reach names."""
    full = make_rules()
    without_literal = Rules(exif=full.exif, rules=(EMAIL, PHONE, ENTITIES), log_key=KEY)
    rows = draw()
    names = stand_in_names(rows, without_literal)
    found = gate_5.residues(all_seeds(rows), names, gate_5.replacement_tokens(full.rules))
    hits = {(s.kind, s.label) for s, hit in zip(all_seeds(rows), found, strict=True) if hit}
    assert hits == {("literal", "")}


# --- the public lines and the verdict (TST-016.D1, D3) ----------------------------------


def test_a_wrong_name_count_fails() -> None:
    assert gate_5.judge_names(499, [False]) == (
        False,
        "names: the run did not make 500 names: FAIL",
    )


def test_the_failing_line_carries_no_residue_count() -> None:
    _, line = gate_5.judge_names(500, [True, True, False])
    assert re.findall(r"\d+", line) == ["500", "0"]


def test_the_exit_follows_the_synthetic_section_only() -> None:
    passed = gate_5.verdict((True, "names: ok"), "real names (box-only, informational): FAIL")
    assert passed.passed
    assert passed.lines[-1] == f"gate 5 PASS: {gate_5.CRITERION}"
    failed = gate_5.verdict((False, "names: FAIL"), "real names (box-only, informational): ok")
    assert not failed.passed
    assert failed.lines[-1].startswith("gate 5 FAIL: ")


def test_the_criterion_says_the_names_are_synthetic() -> None:
    assert "synthetic" in gate_5.CRITERION
    assert "real images" not in gate_5.CRITERION


def test_detail_lines_carry_digests_never_values() -> None:
    rules = make_rules()
    rows = draw()
    names = stand_in_names(rows, rules, leak=True)
    found = gate_5.residues(all_seeds(rows), names)
    lines = gate_5.detail_lines(rows, found, KEY)
    assert lines and len(lines) == sum(found)
    text = "\n".join(lines).casefold()
    for s in all_seeds(rows):
        assert s.value.casefold() not in text
        for word in s.words:
            assert word.casefold() not in text
    for row, name in zip(rows, names, strict=True):
        if row.template != "hash":  # that name is the short hash, which detail lines show
            assert name not in text
    assert all(re.search(r"#[0-9a-f]{12}$", line) for line in lines)
    other = gate_5.detail_lines(rows, found, log_key({LOG_KEY_ENV: "ff" * 16}))
    assert other != lines  # keyed: the digest is not a plain hash of the value


# --- privacy: reprs, the local values in memory only ------------------------------------


def test_reprs_never_show_a_seed_a_path_or_a_caption() -> None:
    rows = draw()
    held_secret = [s for s in all_seeds(rows) if s.kind == "literal"]
    assert held_secret and all(SECRET.split()[1].casefold() in s.value.casefold()
                               for s in held_secret)  # fmt: skip
    for row in rows:
        shown = (repr(row) + repr(row.caption) + "".join(map(repr, row.seeds))).casefold()
        assert "plonkravel" not in shown
        assert row.path.casefold() not in shown
        assert row.caption.subject.casefold() not in shown
        for s in row.seeds:
            assert s.value.casefold() not in shown


def test_local_values_stay_in_memory_and_out_of_the_committed_replay_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The lead's approval: a seeded path or caption that holds a local `literal` value is
    built in memory at gate time, never written to the repo or to tests/recordings/."""
    planted = [f"Vq{uuid.uuid4().hex[:8]} Drelmorth", f"Kz{uuid.uuid4().hex[:8]}"]
    rules_file = tmp_path / "sanitize.yaml"
    rules_file.write_text(
        "exif:\n  mode: strip_all\nrules:\n  - id: mine\n    type: literal\n"
        f'    values: [{planted[0]!r}, {planted[1]!r}]\n    replace: "[PERSON]"\n',
        encoding="utf-8",
    )
    rules = load_rules(rules_file, {LOG_KEY_ENV: KEY_HEX})

    def refuse(*args: object, **kwargs: object) -> None:
        raise AssertionError("the draw wrote to the filesystem")

    real_open = builtins.open

    def read_only_open(file: object, mode: str = "r", *args: object, **kwargs: object):
        if any(flag in mode for flag in "wax+"):
            refuse()
        return real_open(file, mode, *args, **kwargs)  # type: ignore[call-overload]

    with monkeypatch.context() as patch:
        patch.setattr(builtins, "open", read_only_open)
        patch.setattr(Path, "write_text", refuse)
        patch.setattr(Path, "write_bytes", refuse)
        patch.setattr(os, "open", refuse)
        rows = gate_5.draw_rows(gate_5.literal_values(rules.rules), NAMES)
        gate_5.check_held(rows)

    held_values = {s.value.casefold() for s in all_seeds(rows) if s.kind == "literal"}
    for value in planted:
        assert any(value.split()[0].casefold() in v for v in held_values)  # held first
    committed = [SCRIPT, *sorted((REPO / "tests" / "recordings").rglob("*"))]
    for path in committed:
        if path.is_file():
            text = path.read_bytes().decode("utf-8", "replace").casefold()
            for value in planted:
                assert value.split()[0].casefold() not in text, path.name


# --- main --------------------------------------------------------------------------------


def test_main_refuses_unknown_arguments(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_5.main(["--names-from", "x"]) == 1
    assert capsys.readouterr().err == "gate 5 FAIL: usage: gate_5.py [--detail]\n"


def test_main_fails_until_the_runner_lands(capsys: pytest.CaptureFixture[str]) -> None:
    assert gate_5.main([]) == 1
    err = capsys.readouterr().err
    assert err.startswith("gate 5 FAIL: ") and "TST-016.1.3" in err
