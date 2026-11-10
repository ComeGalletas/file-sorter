"""TST-008.3.3: gate 3's runner pieces, with fakes (no db, no images, no models).

The end-to-end run on synthetic images is tests/integration/test_gate_3_script.py. The real
fixtures only run at `make gate-3` (TST-004).
"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_3.py"
_spec = importlib.util.spec_from_file_location("gate_3_runner", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_3)

PLANTED = "Qzxv-Planted-Secret"
IMAGES = Path("/synthetic/images")


def node(name: str):
    return SimpleNamespace(name=name)


def test_gate_nodes_picks_the_three_in_order() -> None:
    registry = [node("classify"), node("caption"), node("sanitize"), node("ingest")]
    assert [n.name for n in gate_3.gate_nodes(registry)] == ["ingest", "sanitize", "classify"]


def test_gate_nodes_without_classify_is_a_setup_error_with_no_cause() -> None:
    with pytest.raises(gate_3.GateSetupError) as caught:
        gate_3.gate_nodes([node("ingest"), node("sanitize")])
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_relative_name_strips_the_images_folder() -> None:
    assert gate_3.relative_name("/synthetic/images/a/b.png", IMAGES) == "a/b.png"
    assert gate_3.relative_name("/elsewhere/b.png", IMAGES) is None


def test_to_outcomes_maps_duplicates_and_rejects_foreign_paths() -> None:
    rows = [
        (
            "/synthetic/images/a.png",
            ["/synthetic/images/d/a2.png"],
            "classified",
            "f",
            "t",
            "safe",
            "safe",
        )
    ]
    (outcome,) = gate_3.to_outcomes(rows, IMAGES)
    assert outcome.names == ("a.png", "d/a2.png") and outcome.branch == "safe"
    assert outcome.nsfw_level == "safe"
    bad = [("/elsewhere/a.png", None, "classified", None, None, None, None)]
    with pytest.raises(gate_3.GateRunError) as caught:
        gate_3.to_outcomes(bad, IMAGES)
    assert "elsewhere" not in str(caught.value)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_prerequisites_name_what_is_missing(tmp_path: Path) -> None:
    with pytest.raises(gate_3.GateSetupError, match="DB_DSN"):
        gate_3.check_prerequisites(None, tmp_path)
    with pytest.raises(gate_3.GateSetupError, match="missing or empty"):
        gate_3.check_prerequisites("postgresql://x", tmp_path)  # empty folder
    (tmp_path / "x").write_bytes(b"")
    assert gate_3.check_prerequisites("postgresql://x", tmp_path) == "postgresql://x"


def test_main_setup_failure_exits_1_with_fixed_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DB_DSN", raising=False)
    assert gate_3.main([], registry=[]) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "DB_DSN" in captured.err


def test_main_unexpected_error_prints_the_type_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", f"postgresql://{PLANTED}@h/db")

    def boom(*_args: object) -> None:
        raise RuntimeError(PLANTED)

    monkeypatch.setattr(gate_3, "run_pipeline", boom)
    registry = [node("ingest"), node("sanitize"), node("classify")]
    assert gate_3.main([], images=tmp_path, registry=registry) == 1
    captured = capsys.readouterr()
    assert PLANTED not in captured.out + captured.err
    assert "RuntimeError" in captured.err


def test_main_labels_error_prints_its_fixed_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", "postgresql://h/db")

    def bad_labels(*_args: object) -> None:
        raise gate_3.fixture_labels.LabelsError("labels line 4, column topic: unknown")

    monkeypatch.setattr(gate_3, "run_pipeline", bad_labels)
    registry = [node("ingest"), node("sanitize"), node("classify")]
    assert gate_3.main([], images=tmp_path, registry=registry) == 1
    assert "labels line 4, column topic" in capsys.readouterr().err


def test_main_prints_public_form_by_default_and_detail_on_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", "postgresql://h/db")
    labels = gate_3.fixture_labels.parse_labels(
        "file,format,topic,adult,reference,subject,tags\n"
        "a.png,zorbs,plinth,yes,,,\nb.png,zorbs,plinth,no,,,suggestive-negative\n",
        formats={"zorbs"},
        topics={"plinth"},
    )
    outs = [
        gate_3.Outcome(("a.png",), "classified", "zorbs", "plinth", "nsfw", "nudity"),
        gate_3.Outcome(("b.png",), "classified", "zorbs", "plinth", "safe", "safe"),
    ]
    monkeypatch.setattr(gate_3, "run_pipeline", lambda *_a: gate_3.evaluate(labels, outs, 2))
    registry = [node("ingest"), node("sanitize"), node("classify")]
    assert gate_3.main([], images=tmp_path, registry=registry) == 0
    plain = capsys.readouterr().out
    assert plain.splitlines()[0] == "category descriptions: seeded"
    assert plain.splitlines()[-1] == "gate 3 PASS"
    assert "DETAIL" not in plain and "zorbs" not in plain
    assert gate_3.main(["--detail"], images=tmp_path, registry=registry) == 0
    detailed = capsys.readouterr().out
    assert "DETAIL" in detailed and "never paste" in detailed


# TST-013.D1: --categories-from-app-db. Fakes only; planted values must never be printed.


def _eval_module():
    import eval.classify_eval as classify_eval

    return classify_eval


def _passing(labels_outs: tuple) -> object:
    labels, outs = labels_outs
    return gate_3.evaluate(labels, outs, 2)


def _one_passing_row() -> tuple:
    labels = gate_3.fixture_labels.parse_labels(
        "file,format,topic,adult,reference,subject,tags\n"
        "a.png,zorbs,plinth,yes,,,\nb.png,zorbs,plinth,no,,,suggestive-negative\n",
        formats={"zorbs"},
        topics={"plinth"},
    )
    outs = [
        gate_3.Outcome(("a.png",), "classified", "zorbs", "plinth", "nsfw", "nudity"),
        gate_3.Outcome(("b.png",), "classified", "zorbs", "plinth", "safe", "safe"),
    ]
    return labels, outs


REGISTRY = [node("ingest"), node("sanitize"), node("classify")]


def test_app_flag_without_a_dsn_is_a_setup_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", "postgresql://h/db")
    monkeypatch.delenv("APP_DB_DSN", raising=False)
    assert gate_3.main([gate_3.APP_FLAG], images=tmp_path, registry=REGISTRY) == 1
    captured = capsys.readouterr()
    assert captured.out == "" and "APP_DB_DSN is not set" in captured.err


def test_app_flag_read_failure_prints_fixed_text_only(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", "postgresql://h/db")
    monkeypatch.setenv("APP_DB_DSN", f"postgresql://u:{PLANTED}@db/x")
    ce = _eval_module()

    def refuse(dsn: str | None, connect: object = None) -> None:
        raise ce.EvalError("the app database cannot be read")

    monkeypatch.setattr(ce, "read_app_categories", refuse)
    assert gate_3.main([gate_3.APP_FLAG], images=tmp_path, registry=REGISTRY) == 1
    captured = capsys.readouterr()
    assert PLANTED not in captured.out + captured.err
    assert "the app database cannot be read" in captured.err


def test_read_app_error_is_unchained() -> None:
    with pytest.raises(gate_3.GateSetupError) as caught:
        gate_3.read_app(None)
    assert caught.value.__cause__ is None and caught.value.__context__ is None


def test_app_flag_passes_the_categories_and_says_where_they_came_from(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", "postgresql://h/db")
    monkeypatch.setenv("APP_DB_DSN", f"postgresql://u:{PLANTED}@db/x")
    ce = _eval_module()
    planted = ce.AppCategory("topic", "qorvex", "Qorvex", "any", PLANTED, None)
    monkeypatch.setattr(ce, "read_app_categories", lambda dsn, connect=None: [planted])
    seen: list[object] = []

    def fake_run(*args: object) -> object:
        seen.append(args[-1])
        return _passing(_one_passing_row())

    monkeypatch.setattr(gate_3, "run_pipeline", fake_run)
    assert gate_3.main([gate_3.APP_FLAG], images=tmp_path, registry=REGISTRY) == 0
    out = capsys.readouterr().out
    assert seen == [[planted]]
    assert out.splitlines()[0] == "category descriptions: app database"
    assert PLANTED not in out and "qorvex" not in out.lower()


def test_without_the_flag_no_app_categories_are_read(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    (tmp_path / "x").write_bytes(b"")
    monkeypatch.setenv("DB_DSN", "postgresql://h/db")
    ce = _eval_module()

    def must_not_read(*_a: object, **_k: object) -> None:
        raise AssertionError("read without the flag")

    monkeypatch.setattr(ce, "read_app_categories", must_not_read)
    seen: list[object] = []

    def fake_run(*args: object) -> object:
        seen.append(args[-1])
        return _passing(_one_passing_row())

    monkeypatch.setattr(gate_3, "run_pipeline", fake_run)
    assert gate_3.main([], images=tmp_path, registry=REGISTRY) == 0
    assert seen == [None]


def test_apply_app_fails_the_gate_when_a_category_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ce = _eval_module()

    class Conn:
        def __enter__(self) -> "Conn":
            return self

        def __exit__(self, *_a: object) -> None:
            return None

        def commit(self) -> None:
            return None

    monkeypatch.setattr(ce, "apply_app_categories", lambda conn, app: 1)
    with pytest.raises(gate_3.GateSetupError, match="could not be applied") as caught:
        gate_3.apply_app("postgresql://h/db", [], connect=lambda *_a: Conn())
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    monkeypatch.setattr(ce, "apply_app_categories", lambda conn, app: 0)
    # nothing skipped: no error
    gate_3.apply_app("postgresql://h/db", [], connect=lambda *_a: Conn())
