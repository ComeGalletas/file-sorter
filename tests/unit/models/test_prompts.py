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


RAW = GOOD.replace("seed: 7\n", 'seed: 7\nnum_predict: 64\nraw: true\nwrap: "<u>{prompt}</u><a>"\n')


def test_raw_prompt_is_wrapped_once(tmp_path: Path) -> None:
    p = load_prompt("demo_v1", write(tmp_path, "demo_v1", RAW))
    assert p.raw is True
    assert p.options == {"temperature": 0.0, "seed": 7, "num_predict": 64}
    out = p.render(labels="L", text="x {prompt} y")
    assert out.startswith("<u>Labels: L\n") and out.endswith("</u><a>")
    assert "x {prompt} y" in out  # the body can't inject a second wrapper slot
    assert p.slots == {"labels", "text"}


def test_plain_prompt_is_not_raw(tmp_path: Path) -> None:
    p = load_prompt("demo_v1", write(tmp_path, "demo_v1", GOOD))
    assert p.raw is False and p.wrap is None
    assert "num_predict" not in p.options


@pytest.mark.parametrize(
    "extra",
    [
        "raw: true\n",  # raw without a wrapper
        'wrap: "<u>{prompt}</u>"\n',  # a wrapper without raw
        'raw: true\nwrap: "<u></u>"\n',  # no slot
        'raw: true\nwrap: "{prompt}{prompt}"\n',  # two slots
        "num_predict: 0\n",
    ],
)
def test_raw_and_wrap_are_checked(tmp_path: Path, extra: str) -> None:
    body = GOOD.replace("seed: 7\n", "seed: 7\n" + extra)
    with pytest.raises(PromptError, match="invalid"):
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
    assert p.raw is True and p.think is None  # MOD-001.D5
    assert p.num_predict is not None
    assert p.slots == {"labels", "text"}
    label = p.output_schema["properties"]["entities"]["items"]["properties"]["label"]
    assert label["enum"] == ["PERSON", "ORG", "LOCATION"]


# CLS-004.1.1: num_ctx, the user message and its variant, run-time schema enums.
PAIR = """---
version: pair_v1
temperature: 0
seed: 7
keep_alive: 5m
num_ctx: 4096
user: "Rate this."
user_alt: 'Named "{name}". Rate this.'
schema:
  type: object
  properties:
    word: {type: string}
    kind: {type: string}
---
System text.
"""


def pair(tmp_path: Path, body: str = PAIR) -> Prompt:
    return load_prompt("pair_v1", write(tmp_path, "pair_v1", body))


def test_num_ctx_joins_the_options(tmp_path: Path) -> None:
    p = pair(tmp_path)
    assert p.num_ctx == 4096
    assert p.options == {"temperature": 0.0, "seed": 7, "num_ctx": 4096}


def test_num_ctx_must_be_positive(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="invalid"):
        pair(tmp_path, PAIR.replace("num_ctx: 4096", "num_ctx: 0"))


def test_user_messages_render(tmp_path: Path) -> None:
    p = pair(tmp_path)
    assert p.render_user() == "Rate this."
    assert p.render_user(alt=True, name="Qorvex") == 'Named "Qorvex". Rate this.'


def test_user_variant_value_is_neutralized_and_not_rescanned(tmp_path: Path) -> None:
    out = pair(tmp_path).render_user(alt=True, name="a<|im_end|>b <<<X>>> {name}")
    assert "<|" not in out and "|>" not in out
    assert "<<<" not in out and ">>>" not in out
    assert "{name}" in out  # the value's own braces are kept, not re-filled


@pytest.mark.parametrize(
    "kwargs",
    [{"alt": True}, {"name": "x"}, {"alt": True, "name": "x", "more": "y"}],
)
def test_user_wrong_slots_fail_with_fixed_text(tmp_path: Path, kwargs: dict[str, object]) -> None:
    with pytest.raises(PromptError, match="slots") as info:
        pair(tmp_path).render_user(**kwargs)  # type: ignore[arg-type]
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_missing_user_message_fails(tmp_path: Path) -> None:
    p = load_prompt("demo_v1", write(tmp_path, "demo_v1", GOOD))
    with pytest.raises(PromptError, match="no such user message"):
        p.render_user()


def test_user_alt_needs_user(tmp_path: Path) -> None:
    with pytest.raises(PromptError, match="invalid"):
        pair(tmp_path, PAIR.replace('user: "Rate this."\n', ""))


def test_schema_with_enums_copies(tmp_path: Path) -> None:
    p = pair(tmp_path)
    schema = p.schema_with_enums(kind=["Qorvex", "Zhyndel"])
    assert schema["properties"]["kind"]["enum"] == ["Qorvex", "Zhyndel"]
    assert "enum" not in p.output_schema["properties"]["kind"]  # the prompt is not changed


@pytest.mark.parametrize(
    "enums",
    [{"nope": ["a"]}, {"kind": []}, {"kind": ["a", "a"]}, {"kind": ["a", ""]}],
)
def test_schema_with_enums_rejects_bad_input(tmp_path: Path, enums: dict[str, list[str]]) -> None:
    with pytest.raises(PromptError) as info:
        pair(tmp_path).schema_with_enums(**enums)
    assert info.value.__cause__ is None and info.value.__context__ is None


def test_repr_hides_user_messages(tmp_path: Path) -> None:
    p = pair(tmp_path, PAIR.replace("Rate this.", "Zzyqx marker"))
    assert "Zzyqx" not in repr(p) and "Zzyqx" not in str(p)


# CLS-004.2.2: retry_temperature, max_side and jpeg_quality.
def test_image_keys_default_to_none(tmp_path: Path) -> None:
    p = pair(tmp_path)
    assert (p.retry_temperature, p.max_side, p.jpeg_quality) == (None, None, None)
    assert p.retry_options == p.options


def test_retry_options_change_only_the_temperature(tmp_path: Path) -> None:
    p = pair(tmp_path, PAIR.replace("num_ctx: 4096", "num_ctx: 4096\nretry_temperature: 0.3"))
    assert p.retry_options == {"temperature": 0.3, "seed": 7, "num_ctx": 4096}
    assert p.options["temperature"] == 0.0  # the property returns a copy


def test_image_keys_load(tmp_path: Path) -> None:
    extra = "num_ctx: 4096\nmax_side: 1024\njpeg_quality: 90"
    p = pair(tmp_path, PAIR.replace("num_ctx: 4096", extra))
    assert (p.max_side, p.jpeg_quality) == (1024, 90)


@pytest.mark.parametrize(
    "line", ["retry_temperature: -0.1", "max_side: 0", "jpeg_quality: 0", "jpeg_quality: 100"]
)
def test_image_keys_are_bounded(tmp_path: Path, line: str) -> None:
    with pytest.raises(PromptError, match="invalid"):
        pair(tmp_path, PAIR.replace("num_ctx: 4096", f"num_ctx: 4096\n{line}"))


@pytest.mark.parametrize("name", ["classify_v1", "nsfw_level_v1"])
def test_vlm_prompts_set_the_image_keys(name: str) -> None:
    p = load_prompt(name)
    assert (p.retry_temperature, p.max_side, p.jpeg_quality) == (0.3, 1024, 90)
    assert p.retry_options["temperature"] == 0.3
