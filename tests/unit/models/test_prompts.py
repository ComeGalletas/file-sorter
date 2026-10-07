"""MOD-001.2.1: prompt files with front matter (MOD-001.D1, R-CAP-3)."""

from pathlib import Path

import pytest

from classifier.models.prompts import PROMPTS_DIR, Prompt, PromptError, load_prompt

GOOD = """---
version: demo_v1
temperature: 0
seed: 7
keep_alive: 5m
schema:
  type: object
  properties:
    word: {type: string}
---
Labels: {labels}
Answer like {"word": "x"}.
<<<{text}>>>
"""


def write(tmp_path: Path, name: str, body: str) -> Path:
    (tmp_path / f"{name}.md").write_text(body, encoding="utf-8")
    return tmp_path


def test_front_matter_is_parsed(tmp_path: Path) -> None:
    p = load_prompt("demo_v1", write(tmp_path, "demo_v1", GOOD))
    assert p.version == "demo_v1"
    assert p.options == {"temperature": 0.0, "seed": 7}
    assert p.keep_alive == "5m"
    assert p.think is None
    assert p.output_schema["properties"]["word"] == {"type": "string"}
    assert p.slots == {"labels", "text"}


def test_crlf_file_loads(tmp_path: Path) -> None:
    body = GOOD.replace("\n", "\r\n")
    (tmp_path / "demo_v1.md").write_bytes(body.encode("utf-8"))
    assert load_prompt("demo_v1", tmp_path).version == "demo_v1"


def test_render_fills_slots_once_and_keeps_json_braces(tmp_path: Path) -> None:
    p = load_prompt("demo_v1", write(tmp_path, "demo_v1", GOOD))
    out = p.render(labels="PERSON", text="a {labels} b")
    assert "Labels: PERSON" in out
    assert "<<<a {labels} b>>>" in out  # a value is never re-scanned
    assert '{"word": "x"}' in out


@pytest.mark.parametrize("values", [{"labels": "X"}, {"labels": "X", "text": "y", "more": "z"}])
def test_render_wrong_slots(tmp_path: Path, values: dict[str, str]) -> None:
    p = load_prompt("demo_v1", write(tmp_path, "demo_v1", GOOD))
    with pytest.raises(PromptError, match="slots"):
        p.render(**values)


@pytest.mark.parametrize(
    ("body", "match"),
    [
        ("no front matter\n", "no front matter"),
        ("---\n- a list\n---\nbody\n", "not a mapping"),
        ("---\nversion: [unclosed\n---\nbody\n", "not YAML"),
        (GOOD.replace("seed: 7\n", ""), "invalid"),
        (GOOD.replace("seed: 7\n", "seed: 7\nextra: 1\n"), "invalid"),
        (GOOD.replace("seed: 7\n", "seed: 7\ntemplate: x\n"), "template"),
        (GOOD.replace("version: demo_v1", "version: other_v1"), "declares version"),
    ],
)
def test_malformed_files_are_refused(tmp_path: Path, body: str, match: str) -> None:
    with pytest.raises(PromptError, match=match):
        load_prompt("demo_v1", write(tmp_path, "demo_v1", body))


@pytest.mark.parametrize("name", ["../x", "a/b", "A_v1", "", "x.md"])
def test_bad_names_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(PromptError, match="invalid prompt name"):
        load_prompt(name, tmp_path)


def test_missing_file(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="cannot read"):
        load_prompt("absent_v1", tmp_path)


def test_entity_prompt_ships_with_its_front_matter() -> None:
    p = load_prompt("sanitize_entity_v1")
    assert isinstance(p, Prompt)
    assert (PROMPTS_DIR / "sanitize_entity_v1.md").is_file()
    assert p.temperature == 0
    assert p.slots == {"labels", "text"}
    label = p.output_schema["properties"]["entities"]["items"]["properties"]["label"]
    assert label["enum"] == ["PERSON", "ORG", "LOCATION"]
