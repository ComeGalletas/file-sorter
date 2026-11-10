"""CLS-004.5: the VLM-path eval harness, on a scripted VLM client and synthetic rows.

Every image, label, category and hint is a synthetic coinage; no model, fixture or Ollama is
reached. The throwaway-database run (`collect`) is covered by the gpu tier.
"""

import json
import re
import sys
from pathlib import Path

import httpx
import numpy as np
import pytest
from PIL import Image

REPO = Path(__file__).resolve().parents[3]
for folder in (REPO / "eval", REPO / "scripts"):
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))

import classify_eval as ev  # noqa: E402
import gate_3 as gate  # noqa: E402
from fixture_labels import parse_labels  # noqa: E402

from classifier.config import NsfwConfig, NsfwLevel  # noqa: E402
from classifier.models import vlm_classify as vlm_module  # noqa: E402
from classifier.models.classify_rules import CategoryRule  # noqa: E402
from classifier.models.ollama import OllamaClient, OllamaUnavailable  # noqa: E402
from classifier.models.prompts import load_effective_prompt  # noqa: E402

HOST = "http://ollama"
MODEL = "synthetic-vlm:1b"
FORMATS = ["Qorvex", "Zhyndel", "unsorted"]
TOPICS = ["Vrellik", "Xandoz"]
HASH = "ab" * 32
SECRET = "plantedsecret_zq"


def scripted(*replies) -> tuple[OllamaClient, list[dict]]:
    seen: list[dict] = []
    queue = list(replies)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        reply = queue.pop(0)
        if isinstance(reply, type):
            raise reply("synthetic failure", request=request)
        return httpx.Response(200, json={"response": json.dumps(reply)})

    return OllamaClient(HOST, transport=httpx.MockTransport(handler)), seen


def classify_reply(fmt="Qorvex", topic="Vrellik") -> dict:
    return {"observation": "synthetic cues", "format": fmt, "topic": topic}


def level_reply(level="safe") -> dict:
    return {"observation": "synthetic cues", "nsfw_level": level, "traces": False}


class FakeBackend:
    nsfw_id = "fake-nsfw"

    def __init__(self, score: float = 0.25) -> None:
        self.score = score
        self.calls = 0

    def nsfw_scores(self, images):
        self.calls += len(images)
        return np.array([self.score for _ in images], dtype=np.float32)


def make_work(folder: Path, digest: str = HASH) -> Path:
    work = folder / ".work"
    work.mkdir()
    Image.new("RGB", (16, 16), (10, 120, 200)).save(work / f"{digest}.png")
    return work


def row(hint: str | None = "Hintqorvex") -> ev._Row:
    return ev._Row(HASH, "png", hint)


# --- Prompt versions --------------------------------------------------------------------------


@pytest.fixture
def prompts_dir(tmp_path, monkeypatch):
    """A copy of the committed prompts with an empty `local/`, local prompts on."""
    monkeypatch.delenv("PROMPTS_LOCAL", raising=False)
    folder = tmp_path / "prompts"
    (folder / "local").mkdir(parents=True)
    for name in ev.PROMPT_NAMES:
        (folder / f"{name}.md").write_bytes((ev.PROMPTS_DIR / f"{name}.md").read_bytes())
    return folder


def test_the_local_prompts_line_says_present_or_absent_and_never_a_hash(prompts_dir):
    bare = ev.local_prompt_lines(ev.effective_prompts(prompts_dir))
    assert bare == ["local prompts: classify_v1 absent, nsfw_level_v1 absent"]
    (prompts_dir / "local" / "classify_v1.md").write_text(f"{SECRET} replacement", encoding="utf-8")
    prompts = ev.effective_prompts(prompts_dir)
    lines = ev.local_prompt_lines(prompts)
    assert lines == [
        "local prompts: classify_v1 present, nsfw_level_v1 absent",
        "with the provisional H8 local prompts",
    ]
    line = " | ".join(lines)
    assert SECRET not in line and not re.search(r"[0-9a-f]{8}", line)


def test_the_versions_line_carries_the_hash_for_the_console_only(prompts_dir):
    (prompts_dir / "local" / "classify_v1.md").write_text(f"{SECRET} replacement", encoding="utf-8")
    prompts = ev.effective_prompts(prompts_dir)
    line = ev.versions_line(prompts)
    assert re.fullmatch(
        r"effective prompts \(console only\): classify_v1\+[0-9a-f]{8}, nsfw_level_v1", line
    )
    assert SECRET not in line


def test_the_local_off_switch_ignores_the_replacement(prompts_dir, monkeypatch):
    (prompts_dir / "local" / "classify_v1.md").write_text("a replacement", encoding="utf-8")
    monkeypatch.setenv("PROMPTS_LOCAL", "off")
    assert ev.local_prompt_lines(ev.effective_prompts(prompts_dir)) == [
        "local prompts: classify_v1 absent, nsfw_level_v1 absent"
    ]


def test_the_file_digest_ignores_the_replacement_and_a_missing_file_is_unchained(prompts_dir):
    before = ev.prompt_file_digest("classify_v1", prompts_dir)
    (prompts_dir / "local" / "classify_v1.md").write_text("a replacement", encoding="utf-8")
    assert ev.prompt_file_digest("classify_v1", prompts_dir) == before
    with pytest.raises(ev.EvalError) as caught:
        ev.prompt_file_digest("classify_v1", prompts_dir / "nowhere")
    assert str(caught.value) == "a prompt file cannot be read"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


# --- The cache --------------------------------------------------------------------------------


def test_the_cache_key_changes_with_each_ingredient():
    base = ev.cache_key(MODEL, ["h1", "h2"], NsfwLevel.nudity, FORMATS, TOPICS)
    assert base == ev.cache_key(MODEL, ["h1", "h2"], NsfwLevel.nudity, FORMATS, TOPICS)
    assert base != ev.cache_key("other:1b", ["h1", "h2"], NsfwLevel.nudity, FORMATS, TOPICS)
    assert base != ev.cache_key(MODEL, ["h1", "h3"], NsfwLevel.nudity, FORMATS, TOPICS)
    assert base != ev.cache_key(MODEL, ["h1", "h2"], NsfwLevel.explicit, FORMATS, TOPICS)
    assert base != ev.cache_key(MODEL, ["h1", "h2"], NsfwLevel.nudity, FORMATS[:2], TOPICS)
    assert base != ev.cache_key(MODEL, ["h1", "h2"], NsfwLevel.nudity, FORMATS, TOPICS[:1])


def test_the_cache_round_trips_answers_by_hash_and_holds_nothing_else(tmp_path):
    answers = {
        HASH: ev.Answer("Qorvex", "Vrellik", "suggestive", 0.5),
        "cd" * 32: ev.Answer("unsorted", None, "safe", None),
    }
    assert ev.save_cache(tmp_path, "k", answers)
    assert ev.load_cache(tmp_path, "k") == answers
    on_disk = json.loads((tmp_path / "k.json").read_text(encoding="utf-8"))
    assert set(on_disk) == {"answers"}
    for entry in on_disk["answers"].values():
        assert set(entry) == {"format", "topic", "level", "nsfw", "traces"}
    assert not list(tmp_path.glob("*.tmp"))


def test_a_corrupt_unknown_or_missing_cache_is_ignored(tmp_path):
    assert ev.load_cache(tmp_path, "absent") == {}
    (tmp_path / "bad.json").write_text("not json", encoding="utf-8")
    assert ev.load_cache(tmp_path, "bad") == {}
    entry = {"format": "Qorvex", "topic": None, "level": "no-such-level", "nsfw": None}
    (tmp_path / "lvl.json").write_text(json.dumps({"answers": {HASH: entry}}), encoding="utf-8")
    assert ev.load_cache(tmp_path, "lvl") == {}


def test_an_unwritable_cache_is_not_fatal(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x", encoding="utf-8")
    assert not ev.save_cache(blocker / "sub", "k", {})


# --- Judging one image ------------------------------------------------------------------------


def test_an_image_is_asked_with_the_hint_and_the_category_names(tmp_path):
    work = make_work(tmp_path)
    client, seen = scripted(classify_reply("Zhyndel", "Xandoz"), level_reply("suggestive"))
    backend = FakeBackend(0.4)
    found = ev.judge_image(client, MODEL, backend, work, row(), FORMATS, TOPICS)
    assert found is not None
    assert (found.format, found.topic, found.level) == ("Zhyndel", "Xandoz", "suggestive")
    assert found.nsfw == pytest.approx(0.4, abs=1e-6)
    assert "Hintqorvex" in seen[0]["prompt"]  # the sanitized hint reaches the format call only
    assert "Hintqorvex" not in json.dumps(seen[1])
    assert set(seen[0]["format"]["properties"]["format"]["enum"]) >= {"Qorvex", "Zhyndel"}
    assert backend.calls == 1


def test_an_unanswered_image_is_none_and_a_missing_copy_is_none(tmp_path):
    work = make_work(tmp_path)
    bad = {"format": "no-such", "topic": "none"}
    client, _ = scripted(bad, bad)  # both tries fail; the level call never happens
    assert ev.judge_image(client, MODEL, FakeBackend(), work, row(), FORMATS, TOPICS) is None
    client, seen = scripted()
    gone = ev._Row("cd" * 32, "png", None)
    assert ev.judge_image(client, MODEL, FakeBackend(), work, gone, FORMATS, TOPICS) is None
    assert seen == []


def test_ollama_unavailable_stops_the_run(tmp_path):
    work = make_work(tmp_path)
    client, _ = scripted(httpx.ConnectError)
    with pytest.raises(OllamaUnavailable):
        ev.judge_image(client, MODEL, FakeBackend(), work, row(), FORMATS, TOPICS)


def test_a_non_finite_falconsai_score_is_dropped(tmp_path):
    work = make_work(tmp_path)
    client, _ = scripted(classify_reply(), level_reply())
    found = ev.judge_image(client, MODEL, FakeBackend(float("nan")), work, row(), FORMATS, TOPICS)
    assert found is not None and found.nsfw is None


# --- Deciding ---------------------------------------------------------------------------------


def rules() -> list[CategoryRule]:
    out = [
        CategoryRule(1, "format", "Qorvex", "f1", 0.5, "safe", None),
        CategoryRule(2, "format", "Zhyndel", "f2", 0.5, "nsfw", None),
        CategoryRule(3, "format", "unsorted", "f3", None, "safe", None),
        CategoryRule(4, "topic", "Vrellik", "t1", 0.5, "safe", None),
    ]
    return out


NSFW_CONFIG = NsfwConfig.model_validate({"min_level": "nudity", "mode": "mirror", "root": "Adult"})


def test_decide_uses_min_level_and_an_unknown_name_is_an_error():
    adult = ev.Answer("Zhyndel", "Vrellik", "nudity", 0.9)
    choice, level = ev._decide(adult, rules(), NSFW_CONFIG)
    assert (choice.branch, choice.format, level) == ("nsfw", "Zhyndel", "nudity")
    safe = ev.Answer("Qorvex", None, "suggestive", 0.1)
    assert ev._decide(safe, rules(), NSFW_CONFIG)[0].branch == "safe"
    assert ev._decide(None, rules(), NSFW_CONFIG) is None
    assert ev._decide(ev.Answer("Unknownia", None, "safe", None), rules(), NSFW_CONFIG) is None


# --- The report (public form) -----------------------------------------------------------------

LABELS = (
    "file,format,topic,adult,reference,subject,tags,nsfw_level\n"
    "a_qorvex.png,Qorvex,Vrellik,no,,,,safe\n"
    "b_qorvex.png,Qorvex,,no,,,,safe\n"
    "c_zhyndel.png,Zhyndel,Vrellik,yes,,,,explicit\n"
    "d_qorvex.png,Qorvex,,no,,,suggestive-negative,suggestive\n"
)


def outcomes(**changes) -> list[gate.Outcome]:
    rows = {
        "a_qorvex.png": ("Qorvex", "Vrellik", "safe", "safe"),
        "b_qorvex.png": ("Qorvex", None, "safe", "safe"),
        "c_zhyndel.png": ("Zhyndel", "Vrellik", "nsfw", "explicit"),
        "d_qorvex.png": ("Qorvex", None, "safe", "suggestive"),
    } | changes
    return [
        gate.Outcome((name,), "classified", fmt, topic, branch, level)
        for name, (fmt, topic, branch, level) in rows.items()
    ]


def collected(rows: list[gate.Outcome], cross_checked: int = 0, **checks) -> ev.Collected:
    labels = parse_labels(LABELS, formats={"Qorvex", "Zhyndel"}, topics={"Vrellik"})
    measures = gate.evaluate(labels, rows, int(NsfwLevel.nudity))
    flags = {"nsfw_label": True, "nsfw_input": True} | checks
    result = ev.Checks(coverage=measures.coverage_ok, **flags)
    prompts = tuple(
        load_effective_prompt(name).model_copy(update={"replacement_hash": hashed})
        for name, hashed in zip(ev.PROMPT_NAMES, ("0a1b2c3d", None), strict=True)
    )
    return ev.Collected(measures, result, prompts, "nudity", cross_checked)


def test_the_public_form_is_verdicts_whole_percents_and_no_hash():
    lines = ev.render(collected(outcomes()))
    out = "\n".join(lines)
    assert "local prompts: classify_v1 present, nsfw_level_v1 absent" in lines
    assert "with the provisional H8 local prompts" in lines
    assert "0a1b2c3d" not in out and not re.search(r"[0-9a-f]{8}", out)
    assert "bug checks: nsfw label ok, nsfw input ok, coverage ok" in lines
    assert "format agreement: 100% (required >= 80%): ok" in lines
    assert "topic agreement: 100% (required >= 80%): ok" in lines
    assert "unrecognized format: 0% (required < 10%): ok" in lines
    assert "nsfw gate (adult flagged, safe not flagged): ok" in lines
    assert "suggestive-negative rows safe: ok" in lines
    assert "gate 3" not in out  # a report, not a gate
    assert not re.search(r"\d+\.\d+%|\d+/\d+|DETAIL|Falconsai", out)  # no count, no decimal
    assert not re.search(r"[a-d]_(qorvex|zhyndel)", out)  # no file name


def test_failures_say_fail_and_percentages_round_down():
    wrong = outcomes(**{"b_qorvex.png": ("Zhyndel", None, "safe", "safe")})
    out = "\n".join(ev.render(collected(wrong)))
    assert "format agreement: 75% (required >= 80%): FAIL" in out
    leaked = outcomes(**{"d_qorvex.png": ("Qorvex", None, "nsfw", "explicit")})
    out = "\n".join(ev.render(collected(leaked)))
    assert "suggestive-negative rows safe: FAIL" in out
    assert "nsfw gate (adult flagged, safe not flagged): FAIL" in out
    unsorted = outcomes(**{"a_qorvex.png": ("unsorted", None, "safe", "safe")})
    assert "unrecognized format: 25% (required < 10%): FAIL" in "\n".join(
        ev.render(collected(unsorted))
    )


def test_a_failed_check_and_an_error_row_are_reported_as_fail():
    out = "\n".join(ev.render(collected(outcomes(), nsfw_label=False)))
    assert "bug checks: nsfw label FAIL, nsfw input ok, coverage ok" in out
    errored = outcomes()
    errored[0] = gate.Outcome(("a_qorvex.png",), "error", None, None, None, None)
    assert "node errors: FAIL" in "\n".join(ev.render(collected(errored)))


def test_detail_is_console_only_and_adds_the_cross_check_count():
    plain = ev.render(collected(outcomes(), cross_checked=2))
    detailed = ev.render(collected(outcomes(), cross_checked=2), detail=True)
    assert detailed[: len(plain)] == plain
    extra = "\n".join(detailed[len(plain) :])
    assert "DETAIL: box console only" in extra
    assert re.search(r"format \d+\.\d%", extra)
    assert "Falconsai cross-check flags 2 rows" in extra
    assert "effective prompts (console only): classify_v1+0a1b2c3d, nsfw_level_v1" in extra
    assert "Falconsai" not in "\n".join(plain)


# --- Working copies ---------------------------------------------------------------------------


def test_verify_copies_accepts_a_regular_decodable_copy(tmp_path):
    work = make_work(tmp_path)
    assert ev.verify_copies([row()], work)


def test_verify_copies_refuses_a_missing_link_or_non_image(tmp_path):
    work = make_work(tmp_path)
    assert not ev.verify_copies([ev._Row("cd" * 32, "png", None)], work)
    other = "ef" * 32
    (work / f"{other}.png").write_bytes(b"not an image")
    assert not ev.verify_copies([ev._Row(other, "png", None)], work)
    linked = "12" * 32
    try:
        (work / f"{linked}.png").symlink_to(work / f"{HASH}.png")
    except OSError:
        pytest.fail("this test needs symlink support; run it in the test container")
    assert not ev.verify_copies([ev._Row(linked, "png", None)], work)


# --- Privacy ----------------------------------------------------------------------------------


def test_result_types_hold_nothing_planted_in_their_reprs():
    objects = [
        ev.Answer(SECRET, SECRET, SECRET, 0.5),
        ev._Row(SECRET, SECRET, SECRET),
        ev.Checks(True, True, True),
        ev.Collected(
            gate.Measures(
                *(gate.Tally(7, 9) for _ in range(6)), 0, True, ((SECRET, gate.Tally(1, 2)),), ()
            ),
            ev.Checks(True, True, True),
            (load_effective_prompt("classify_v1"),),
            SECRET,
            13,
        ),
    ]
    for obj in objects:
        text = repr(obj) + str(obj)
        assert SECRET not in text


# --- The entry point --------------------------------------------------------------------------


def test_main_without_a_dsn_fails_with_fixed_text(monkeypatch, capsys):
    monkeypatch.delenv("DB_DSN", raising=False)
    assert ev.main([]) == 1
    assert capsys.readouterr().err.strip() == (
        "classify_eval FAIL: DB_DSN is not set: run it in the test container"
    )


def test_main_prints_an_eval_error_as_its_fixed_text(monkeypatch, capsys):
    monkeypatch.setenv("DB_DSN", f"postgres://{SECRET}")

    def boom(*_a, **_k):
        raise ev.EvalError("fixed text")

    monkeypatch.setattr(ev, "run_eval", boom)
    assert ev.main([]) == 1
    assert capsys.readouterr().err.strip() == "classify_eval FAIL: fixed text"


def test_main_prints_the_type_only_for_an_unexpected_error(monkeypatch, capsys):
    monkeypatch.setenv("DB_DSN", f"postgres://{SECRET}")

    def boom(*_a, **_k):
        raise ValueError(SECRET)

    monkeypatch.setattr(ev, "run_eval", boom)
    assert ev.main([]) == 1
    err = capsys.readouterr().err
    assert err.strip() == "classify_eval FAIL: run errored (ValueError)"
    assert SECRET not in err


def test_main_prints_the_report_and_passes_the_flags(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DB_DSN", "postgres://synthetic")
    seen = {}

    def fake(dsn, images, labels, cache, detail, client, backend, from_app_db=False):
        seen.update(cache=cache, detail=detail, images=images, app=from_app_db)
        return ["line one", "line two"]

    monkeypatch.setattr(ev, "run_eval", fake)
    assert ev.main(["--images", str(tmp_path), "--detail", "--no-cache"]) == 0
    assert capsys.readouterr().out == "line one\nline two\n"
    assert seen == {"cache": None, "detail": True, "images": tmp_path, "app": False}
    assert ev.main(["--images", str(tmp_path), "--categories-from-app-db"]) == 0
    assert seen["app"] is True


def test_there_is_no_sweep_option():
    with pytest.raises(SystemExit):
        ev.main(["--slack-points", "1"])


def test_defaults_point_inside_the_repo_and_the_cache_is_ignored():
    assert ev.IMAGES.is_relative_to(ev.REPO) and ev.LABELS.is_relative_to(ev.REPO)
    ignore = (ev.REPO / "eval" / ".gitignore").read_text(encoding="utf-8")
    assert ev.CACHE_DIR.name in ignore


def test_run_eval_without_a_client_or_host_fails_with_fixed_text(monkeypatch, tmp_path):
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    with pytest.raises(ev.EvalError) as caught:
        ev.run_eval("dsn", tmp_path, tmp_path, None, False, None, FakeBackend())
    assert str(caught.value) == "OLLAMA_HOST is not set: run it in the test container"
    assert caught.value.__cause__ is None and caught.value.__context__ is None


# --- CLS-007.3: descriptions, traces and the app database -------------------------------------

FMT_TEXT = "plantedfmt_description_qx"
TOP_TEXT = "plantedtop_description_qx"
DSN_SECRET = "postgresql://user:plantedpw_zq@host/db"


def test_the_descriptions_reach_the_prompt_one_map_per_axis(tmp_path, prompts_dir, monkeypatch):
    # The committed system text doesn't use the slots (CLS-007.D1), so a local replacement that
    # does is what proves the plant is sent. `Qorvex` exists on both axes, one wording each.
    body = "Formats:\n{format_definitions}\nTopics:\n{topic_definitions}\nList: {formats}"
    (prompts_dir / "local" / "classify_v1.md").write_text(body, encoding="utf-8")
    real = vlm_module.load_effective_prompt
    monkeypatch.setattr(vlm_module, "load_effective_prompt", lambda n: real(n, prompts_dir))
    work = make_work(tmp_path)
    client, seen = scripted(classify_reply("Qorvex", "Qorvex"), level_reply())
    ev.judge_image(
        client,
        MODEL,
        FakeBackend(),
        work,
        row(),
        FORMATS,
        ["Qorvex", "Vrellik"],
        {"Qorvex": FMT_TEXT, "Zhyndel": None},
        {"Qorvex": TOP_TEXT},
    )
    sent = json.dumps(seen[0])
    assert f"- Qorvex: {FMT_TEXT}" in sent  # the plant reached the model call
    assert f"- Qorvex: {TOP_TEXT}" in sent
    assert sent.index(FMT_TEXT) != sent.index(TOP_TEXT)
    assert FMT_TEXT not in json.dumps(seen[1]) and TOP_TEXT not in json.dumps(seen[1])


def test_the_traces_flag_is_read_from_the_answer_and_cached(tmp_path):
    work = make_work(tmp_path)
    reply = level_reply() | {"traces": True}
    client, _ = scripted(classify_reply(), reply)
    found = ev.judge_image(client, MODEL, FakeBackend(), work, row(), FORMATS, TOPICS)
    assert found is not None and found.traces is True
    ev.save_cache(tmp_path / "c", "k", {HASH: found})
    assert ev.load_cache(tmp_path / "c", "k")[HASH].traces is True
    # an older cache has no `traces` and reads as False; a non-boolean drops the cache
    folder = tmp_path / "old"
    folder.mkdir()
    old = {"format": "Qorvex", "topic": None, "level": "safe", "nsfw": None}
    (folder / "k.json").write_text(json.dumps({"answers": {HASH: old}}), encoding="utf-8")
    assert ev.load_cache(folder, "k")[HASH].traces is False
    bad = old | {"traces": "yes"}
    (folder / "k.json").write_text(json.dumps({"answers": {HASH: bad}}), encoding="utf-8")
    assert ev.load_cache(folder, "k") == {}


def test_the_cache_key_follows_the_descriptions_and_the_flag():
    base = ("m", ["p"], NsfwLevel.nudity, ["a"], ["b"])

    def key(**kw):
        return ev.cache_key(*base, **kw)

    first = key(format_definitions={"a": "one"}, topic_definitions={"b": "two"})
    assert first != key(format_definitions={"a": "one!"}, topic_definitions={"b": "two"})
    assert first != key(format_definitions={"a": "one"}, topic_definitions={"b": "two!"})
    # the same text on the other axis is a different key: the maps are per axis
    assert first != key(format_definitions={"b": "two"}, topic_definitions={"a": "one"})
    assert first != key(
        format_definitions={"a": "one"}, topic_definitions={"b": "two"}, conservative_traces=True
    )
    assert "one" not in first and "two" not in first


def test_the_floor_reaches_decide_through_the_flag():
    cfg = NsfwConfig.model_validate({"min_level": "suggestive", "mode": "mirror", "root": "Adult"})
    flagged = ev.Answer("Qorvex", None, "safe", None, traces=True)
    assert ev._decide(flagged, rules(), cfg)[0].branch == "safe"
    assert ev._decide(flagged, rules(), cfg, True)[0].branch == "nsfw"
    assert ev._decide(ev.Answer("Qorvex", None, "safe", None), rules(), cfg, True)[0].branch == (
        "safe"
    )


class FakeApp:
    """A stand-in for a psycopg connection that holds the categories table."""

    def __init__(self, rows, fail: bool = False):
        self.rows, self.fail, self.options = rows, fail, None

    def __call__(self, dsn, options=None):
        self.options = options
        if self.fail:
            raise RuntimeError(f"cannot reach {dsn}")
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False

    def execute(self, sql):
        assert sql.lstrip().startswith("select")  # read-only: nothing else is ever sent
        rows = self.rows
        return type("Result", (), {"fetchall": lambda _self: rows})()


def test_the_app_categories_are_read_read_only_per_row():
    fake = FakeApp(
        [
            ("format", "Qorvex", "f1", "any", FMT_TEXT, None),
            ("topic", "Xandoz", "t", "safe", None, "Vrellik"),
        ]
    )
    found = ev.read_app_categories(DSN_SECRET, fake)
    assert "default_transaction_read_only=on" in fake.options
    assert [(c.axis, c.name, c.description, c.parent) for c in found] == [
        ("format", "Qorvex", FMT_TEXT, None),
        ("topic", "Xandoz", None, "Vrellik"),
    ]
    assert FMT_TEXT not in repr(found) + str(found[0])


def test_an_unreachable_app_database_is_fixed_text_and_unchained():
    with pytest.raises(ev.EvalError) as caught:
        ev.read_app_categories(DSN_SECRET, FakeApp([], fail=True))
    assert str(caught.value) == "the app database cannot be read"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert "plantedpw_zq" not in repr(caught.value) + str(caught.value)
    with pytest.raises(ev.EvalError) as missing:
        ev.read_app_categories(None)
    assert str(missing.value) == "APP_DB_DSN is not set: pass it with -e at run time"
    assert missing.value.__cause__ is None and missing.value.__context__ is None


def test_run_eval_reads_the_app_database_only_when_asked(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_DB_DSN", DSN_SECRET)
    asked, got = [], {}

    def source(dsn):
        asked.append(dsn)
        return [ev.AppCategory("format", "Qorvex", "f", "any", FMT_TEXT, None)]

    def fake_collect(*_a, app_categories=None, **_k):
        got["app"] = app_categories
        return collected(outcomes())

    monkeypatch.setattr(ev, "collect", fake_collect)
    client, _ = scripted()
    args = ("dsn", tmp_path, tmp_path, None, False, client, FakeBackend())
    ev.run_eval(*args, app_source=source)
    assert asked == [] and got["app"] is None
    lines = ev.run_eval(*args, from_app_db=True, app_source=source)
    assert asked == [DSN_SECRET] and got["app"][0].description == FMT_TEXT
    assert FMT_TEXT not in "\n".join(lines)


def test_the_report_says_where_the_descriptions_came_from_and_nothing_more():
    import dataclasses

    seeded = ev.render(collected(outcomes()))
    assert "category descriptions: seeded" in seeded
    assert "conservative traces: off" in seeded
    assert not any(line.startswith("categories skipped") for line in seeded)
    # CLS-007.4.2: plant a secret where the human's private wording could ride in (a local
    # prompt's body and user message), and prove it is held by what render receives. render
    # reads only `effective_version` and `replacement_hash` today, so the body and user plants
    # guard against a future read; the hash check below is what render does show.
    private = load_effective_prompt("classify_v1").model_copy(
        update={"template": FMT_TEXT, "user": FMT_TEXT, "replacement_hash": "feedc0de"}
    )
    base = collected(outcomes())
    app = dataclasses.replace(
        base,
        prompts=(private, *base.prompts[1:]),
        descriptions="app database",
        conservative_traces=True,
        skipped=2,
    )
    assert FMT_TEXT in app.prompts[0].template and FMT_TEXT in app.prompts[0].user
    for detail in (False, True):
        out = ev.render(app, detail)
        text = "\n".join(out)
        assert "category descriptions: app database" in out
        assert "conservative traces: on" in out
        assert "categories skipped: 2" in out
        assert FMT_TEXT not in text and "Qorvex" not in text.split("bug checks")[0]
        assert ("feedc0de" in text) is detail  # the local hash is console-only


def test_app_types_hold_nothing_planted_in_their_reprs():
    cat = ev.AppCategory(SECRET, SECRET, SECRET, SECRET, SECRET, SECRET)
    held = (cat.axis, cat.name, cat.folder, cat.branch, cat.description, cat.parent)
    assert all(SECRET in value for value in held)  # every plant is really held
    assert SECRET not in repr(cat) + str(cat)
    # Every Answer field that could carry a value holds a plant, and the plant is really there.
    answer = ev.Answer(SECRET, SECRET + "_t", SECRET + "_l", 0.7391846, traces=True)
    assert SECRET in answer.format and SECRET in answer.topic and SECRET in answer.level
    assert answer.nsfw == 0.7391846
    text = repr(answer) + str(answer)
    assert SECRET not in text and "0.7391846" not in text and "True" not in text
