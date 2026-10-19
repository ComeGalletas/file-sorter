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
    return {"observation": "synthetic cues", "nsfw_level": level}


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
        assert set(entry) == {"format", "topic", "level", "nsfw"}
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
    assert "format agreement: 100% (required >= 85%): ok" in lines
    assert "topic agreement: 100% (required >= 85%): ok" in lines
    assert "unrecognized format: 0% (required < 10%): ok" in lines
    assert "nsfw gate (adult flagged, safe not flagged): ok" in lines
    assert "suggestive-negative rows safe: ok" in lines
    assert "gate 3" not in out  # a report, not a gate
    assert not re.search(r"\d+\.\d+%|\d+/\d+|DETAIL|Falconsai", out)  # no count, no decimal
    assert not re.search(r"[a-d]_(qorvex|zhyndel)", out)  # no file name


def test_failures_say_fail_and_percentages_round_down():
    wrong = outcomes(**{"b_qorvex.png": ("Zhyndel", None, "safe", "safe")})
    out = "\n".join(ev.render(collected(wrong)))
    assert "format agreement: 75% (required >= 85%): FAIL" in out
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

    def fake(dsn, images, labels, cache, detail, client, backend):
        seen.update(cache=cache, detail=detail, images=images)
        return ["line one", "line two"]

    monkeypatch.setattr(ev, "run_eval", fake)
    assert ev.main(["--images", str(tmp_path), "--detail", "--no-cache"]) == 0
    assert capsys.readouterr().out == "line one\nline two\n"
    assert seen == {"cache": None, "detail": True, "images": tmp_path}


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
