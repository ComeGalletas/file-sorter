"""CLI-002.1, CLI-003.1: `classifier dry-run [--csv]` (the acceptance test).

Synthetic images only, generated under `tmp_path`. The command runs `run`, which commits, so
the module has its own migrated schema (`schema_dsn`, tests/integration/conftest.py).
"""

import csv
import re
from collections.abc import Callable, Sequence
from hashlib import sha256
from pathlib import Path

import numpy as np
import psycopg
import pytest
import yaml
from click.testing import Result
from PIL import Image
from typer.testing import CliRunner

from classifier import cli
from classifier.cli import app
from classifier.cli.dry_run_report import COLUMNS, REPORT_FOLDER_FAILED
from classifier.graph import classify as classify_node
from classifier.graph import sanitize as node
from classifier.graph.classify import IMAGE_VEC_DIM
from tests.integration.classify_support import ScriptedVlm

REAL_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"
SOURCE_NAMES = ("alpha.png", "bravo.png", "alpha-copy.png", "notes.txt")
RULES = {
    "exif": {"mode": "strip_all", "keep": ["Orientation", "DateTimeOriginal"]},
    "rules": [{"id": "test-name", "type": "literal", "values": ["Zorvane"], "replace": "[P]"}],
}

pytestmark = pytest.mark.usefixtures("empty_ledger")  # TST-003.1


class FakeVision:
    """A deterministic `VisionBackend` for the CLI (CLI-005.1): hashed embeddings, cosine score.

    Synthetic only. The adult gate reads the red channel of the first pixel, so one made-up
    picture is adult and the others are not; no real model, no real content.
    """

    classifier_id = "fake-classifier"
    nsfw_id = "fake-nsfw"
    logit_scale = 1.0
    logit_bias = 0.0

    @staticmethod
    def _unit(seed: bytes) -> np.ndarray:
        rng = np.random.default_rng(int.from_bytes(sha256(seed).digest()[:8], "big"))
        vector = rng.standard_normal(IMAGE_VEC_DIM).astype(np.float32)
        return vector / np.linalg.norm(vector)

    def embed_images(self, images: Sequence[Image.Image]) -> np.ndarray:
        return np.stack([self._unit(image.tobytes()) for image in images])

    def embed_texts(self, texts: Sequence[str]) -> np.ndarray:
        return np.stack([self._unit(text.encode()) for text in texts])

    def nsfw_scores(self, images: Sequence[Image.Image]) -> np.ndarray:
        return np.array([image.getpixel((0, 0))[0] / 255 for image in images], dtype=np.float32)


@pytest.fixture
def vlm() -> ScriptedVlm:
    return ScriptedVlm()


@pytest.fixture(autouse=True)
def _fake_models(monkeypatch: pytest.MonkeyPatch, vlm: ScriptedVlm) -> None:
    """The dry run runs every M3 node; classify gets the fakes through its two seams."""
    real = cli.run
    monkeypatch.setattr(
        cli,
        "run",
        lambda config, **kw: real(
            config, vision=FakeVision(), ollama_transport=vlm.transport(), **kw
        ),
    )


def _setup(tmp_path: Path, *, results: str = "results") -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    source.mkdir()
    first = source / "alpha.png"
    Image.new("RGB", (8, 6), (10, 20, 30)).save(first)
    Image.new("RGB", (8, 6), (200, 20, 30)).save(source / "bravo.png")
    (source / "alpha-copy.png").write_bytes(first.read_bytes())
    (source / "notes.txt").write_text("not an image")
    data = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    results_root = tmp_path / results
    data["paths"] = {"source_root": str(source), "results_root": str(results_root)}
    data["db"] = {"dsn": None}  # CFG-001.D2: the DSN comes from DB_DSN only
    rules = tmp_path / "rules.yaml"  # synthetic: never the local sanitize.yaml (SAN-001.4)
    rules.write_text(yaml.safe_dump(RULES), encoding="utf-8")
    data["sanitizer"]["rules_file"] = str(rules)
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    return source, results_root, config


def _invoke(config: Path, dsn: str | None = None, *extra: str):
    """`DB_DSN` is set for the call only, or unset when `dsn` is None (CFG-001.D2)."""
    env = {"DB_DSN": dsn}
    return CliRunner().invoke(app, ["dry-run", "--config", str(config), *extra], env=env)


def _tree(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


def _ledger_count(dsn: str) -> int:
    with psycopg.connect(dsn) as conn:
        return conn.execute("select count(*) from files").fetchone()[0]


def test_prints_the_run_counts_without_names(tmp_path: Path, schema_dsn: str) -> None:
    _, _, config = _setup(tmp_path)
    result = _invoke(config, schema_dsn)
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert "new: 2" in out
    assert "skipped-known: 0" in out
    assert "skipped-unreadable: 1" in out
    assert "duplicates: 1" in out
    assert "total: 4" in out
    assert "ledger skipped, " in out and out.count("ledger skipped, ") == 1
    assert not any(name in out for name in SOURCE_NAMES)
    assert "/source" not in out
    assert "sanitized: 2" in out  # CLI-003.1: the duplicate shares its original's row
    assert "sanitize errors: 0" in out
    assert "sanitize error, " not in out
    assert "classified: 2" in out  # CLI-005.1
    assert "classify errors: 0" in out
    assert "classify error, " not in out


def test_csv_lists_the_ledger_rows_by_path(tmp_path: Path, schema_dsn: str) -> None:
    source, results, config = _setup(tmp_path)
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 0, result.output
    reports = list((results / "reports").glob("dry-run-*.csv"))
    assert len(reports) == 1
    assert reports[0].name in result.stdout
    with reports[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))
    assert tuple(rows[0]) == COLUMNS
    body = [dict(zip(COLUMNS, row, strict=True)) for row in rows[1:]]
    assert len(body) == 3  # one row per source_hash: the byte-identical copy is not a row
    paths = [row["source_path"] for row in body]
    assert paths == sorted(paths)
    assert all(Path(p).parent == source for p in paths)
    assert sorted(row["status"] for row in body) == ["classified", "classified", "skipped"]
    skipped = next(row for row in body if row["status"] == "skipped")
    assert skipped["reason"]
    assert all(row["proposed_output"] == "" for row in body)
    assert all(row["short_hash"] == row["source_hash"][:8] for row in body)
    # CLI-003.1: the sanitized stem beside the path; empty where the node hasn't run.
    for row in body:
        expected = Path(row["source_path"]).stem if row["status"] == "classified" else ""
        assert row["sanitized_name"] == expected


def test_writes_only_work_and_reports_under_results_and_nothing_under_source(
    tmp_path: Path, schema_dsn: str
) -> None:
    source, results, config = _setup(tmp_path)
    before = _tree(source)
    assert _invoke(config, schema_dsn, "--csv").exit_code == 0
    assert _tree(source) == before
    # DESIGN §3: before M7 only .work/ (SAN-001.4) and reports/ exist under results_root.
    assert sorted(p.name for p in results.iterdir()) == [".work", "reports"]


def test_without_csv_only_work_is_written_to_results(tmp_path: Path, schema_dsn: str) -> None:
    _, results, config = _setup(tmp_path)
    assert _invoke(config, schema_dsn).exit_code == 0
    assert [p.name for p in results.iterdir()] == [".work"]


def test_second_run_reports_everything_known_and_adds_no_rows(
    tmp_path: Path, schema_dsn: str
) -> None:
    _, _, config = _setup(tmp_path)
    assert _invoke(config, schema_dsn).exit_code == 0
    rows = _ledger_count(schema_dsn)
    second = _invoke(config, schema_dsn)
    assert second.exit_code == 0, second.output
    assert "new: 0" in second.stdout
    assert "skipped-known: 4" in second.stdout
    assert "classified: 0" in second.stdout  # nothing is `sanitized` any more (P-4)
    assert _ledger_count(schema_dsn) == rows == 3


def test_nested_roots_fail_the_root_check(tmp_path: Path, schema_dsn: str) -> None:
    source, _, config = _setup(tmp_path)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["paths"]["results_root"] = str(source / "results")
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code != 0
    assert "R-FOP-9" in result.output
    assert not (source / "results").exists()
    assert _ledger_count(schema_dsn) == 0


def test_missing_config_exits_non_zero(tmp_path: Path) -> None:
    result = _invoke(tmp_path / "absent.yaml")
    assert result.exit_code != 0
    assert "config file not found" in result.output


def test_csv_lists_only_rows_under_the_scanned_root(tmp_path: Path, schema_dsn: str) -> None:
    source, results, config = _setup(tmp_path)
    sibling = str(tmp_path / "source2" / "x.png")  # same prefix as `source`, not under it
    other = str(tmp_path / "elsewhere" / "y.png")
    with psycopg.connect(schema_dsn) as conn:
        for digest, path in (("c" * 64, sibling), ("d" * 64, other)):
            conn.execute(
                "insert into files"
                " (source_hash, short_hash, source_path, source_mtime, ext, status)"
                " values (%s, %s, %s, now(), 'png', 'queued')",
                (digest, digest[:8], path),
            )
    assert _invoke(config, schema_dsn, "--csv").exit_code == 0
    (report,) = (results / "reports").glob("dry-run-*.csv")
    with report.open(encoding="utf-8", newline="") as handle:
        paths = [row["source_path"] for row in csv.DictReader(handle)]
    assert len(paths) == 3
    assert all(Path(p).parent == source for p in paths)
    assert sibling not in paths and other not in paths


def test_validation_error_exits_2_without_echoing_values(tmp_path: Path, schema_dsn: str) -> None:
    _, _, config = _setup(tmp_path)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["thumbs"]["size"] = "SECRET-VALUE-123"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _invoke(config, schema_dsn)
    assert result.exit_code == 2
    assert "thumbs.size" in result.output
    assert "SECRET-VALUE-123" not in result.output
    assert "Traceback" not in result.output


def test_database_error_exits_non_zero_without_echoing_the_dsn(tmp_path: Path) -> None:
    _, _, config = _setup(tmp_path)
    result = _invoke(config, "postgresql://user:hunter2@127.0.0.1:1/db?connect_timeout=2")
    assert result.exit_code == 1
    assert "database error" in result.output
    assert "hunter2" not in result.output
    assert "127.0.0.1" not in result.output


# --- CLI-003.1: the sanitize node in the report ------------------------------------------

# Made-up. SECRET is planted in a folder and a file name and matched by the literal rule:
# it may appear only in the CSV's source_path column. EXC_SECRET rides in an exception.
SECRET = "Zorvane"
EXC_SECRET = "Vexmarrow-exception-secret"
NAMED = Path(f"{SECRET} trip") / f"{SECRET}_beach.png"


def _plant(source: Path) -> Path:
    named = source / NAMED
    named.parent.mkdir()
    Image.new("RGB", (8, 6), (90, 20, 200)).save(named)
    return named


def _assert_clean(result: Result) -> None:
    for secret in (SECRET, EXC_SECRET):
        assert secret not in result.stdout
        assert secret not in result.stderr
    assert "Traceback" not in result.output


def test_a_failed_file_prints_only_its_fixed_reason(
    tmp_path: Path, schema_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _, config = _setup(tmp_path)
    target = sha256((source / "bravo.png").read_bytes()).hexdigest()
    real = node.make_thumbnail

    def failing(copy: Path, *args: object) -> Path:
        if target in copy.name:
            raise OSError(2, EXC_SECRET, f"/source/{SECRET}/{EXC_SECRET}")
        return real(copy, *args)

    monkeypatch.setattr(node, "make_thumbnail", failing)
    result = _invoke(config, schema_dsn)
    assert result.exit_code == 0, result.output
    assert "sanitized: 1" in result.stdout
    assert "sanitize errors: 1" in result.stdout
    assert "sanitize error, sanitize_thumbnail_failed: 1" in result.stdout
    assert result.stdout.count("sanitize error, ") == 1
    _assert_clean(result)


def test_planted_names_reach_only_the_csv_source_path(tmp_path: Path, schema_dsn: str) -> None:
    source, results, config = _setup(tmp_path)
    named = _plant(source)
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 0, result.output
    assert "sanitized: 3" in result.stdout
    _assert_clean(result)
    (report,) = (results / "reports").glob("dry-run-*.csv")
    assert report.resolve().parent == (results / "reports").resolve()
    with report.open(encoding="utf-8", newline="") as handle:
        body = list(csv.DictReader(handle))
    planted = next(row for row in body if row["source_path"] == str(named))
    assert planted["sanitized_name"] == "[P]_beach"  # the literal rule ran on the stem
    for row in body:
        for column, value in row.items():
            if column != "source_path":
                assert SECRET not in value, column


def _absent_rules(data: dict) -> None:
    data["sanitizer"]["rules_file"] = str(Path(data["paths"]["results_root"]).parent / "absent")


def _entity_rule(data: dict) -> None:
    entity = {"id": "test-entity", "type": "entity", "labels": ["PERSON"], "replace": "[E]"}
    rules = {**RULES, "rules": [*RULES["rules"], entity]}
    Path(data["sanitizer"]["rules_file"]).write_text(yaml.safe_dump(rules), encoding="utf-8")


PRE_FLIGHT: dict[str, tuple[Callable[[dict], None] | None, dict[str, None], str]] = {
    # case → (config change, environment unset, a fixed phrase the message must hold)
    "claude-backend": (lambda d: d["sanitizer"].update(backend="claude"), {}, "sanitizer.backend"),
    "missing-log-key": (None, {"SANITIZE_LOG_KEY": None}, "SANITIZE_LOG_KEY"),
    "missing-rules-file": (_absent_rules, {}, "make init"),
    "no-ollama-host": (_entity_rule, {"OLLAMA_HOST": None}, "OLLAMA_HOST"),
    "ocr": (lambda d: d["sanitizer"].update(ocr=True), {}, "sanitizer.ocr"),
}


@pytest.mark.parametrize("case", sorted(PRE_FLIGHT))
def test_a_sanitize_pre_flight_failure_exits_2_with_fixed_text(
    case: str, tmp_path: Path, schema_dsn: str
) -> None:
    """CLI-003.1.3: SanitizeConfigError and the client's OllamaError, with no traceback."""
    source, results, config = _setup(tmp_path)
    _plant(source)
    change, unset, phrase = PRE_FLIGHT[case]
    if change is not None:
        data = yaml.safe_load(config.read_text(encoding="utf-8"))
        change(data)
        config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = CliRunner().invoke(
        app, ["dry-run", "--config", str(config), "--csv"], env={"DB_DSN": schema_dsn, **unset}
    )
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit)
    assert result.stderr.startswith("error: ")
    assert phrase in result.stderr
    assert result.stdout == ""
    _assert_clean(result)
    assert not results.exists()  # refused before .work/ or reports/
    with psycopg.connect(schema_dsn) as conn:
        statuses = {row[0] for row in conn.execute("select status from files")}
    assert "sanitized" not in statuses  # the node rolled back; ingest's rows stay queued


def test_a_work_folder_linked_elsewhere_exits_2(tmp_path: Path, schema_dsn: str) -> None:
    """CLI-003.1.3: WorkDirError (SAN-001.D16) is fixed text too."""
    source, results, config = _setup(tmp_path)
    _plant(source)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    results.mkdir()
    (results / ".work").symlink_to(elsewhere, target_is_directory=True)
    result = _invoke(config, schema_dsn)
    assert result.exit_code == 2, result.output
    assert result.stderr.startswith("error: results_root/.work")
    _assert_clean(result)
    assert list(elsewhere.iterdir()) == []


# --- CLI-005.1: the classify node in the report ------------------------------------------

PINNED_NONE_WIN = [  # the console contract gate 3 may parse; see classifier/cli/__init__.py
    r"run [0-9a-f]{8} \(dry run\)",
    "new: 2",
    "skipped-known: 0",
    "skipped-unreadable: 1",
    "duplicates: 1",
    "total: 4",
    r"ledger skipped, [a-z_ ]+: 1",
    "sanitized: 2",
    "sanitize errors: 0",
    "classified: 2",
    "unsorted: 2",
    "no topic: 2",
    "adult: 1",
    "classify errors: 0",
    r"report: dry-run-\d{8}T\d{6}Z\.csv \(3 rows\)",
]


def _report(results: Path) -> list[dict[str, str]]:
    (path,) = (results / "reports").glob("dry-run-*.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_console_lines_are_pinned_on_a_known_run(
    tmp_path: Path, schema_dsn: str, vlm: ScriptedVlm
) -> None:
    """When the VLM names no format every file is unsorted with no topic; bravo is adult."""
    vlm.unsorted = True
    _, _, config = _setup(tmp_path)
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert len(lines) == len(PINNED_NONE_WIN)
    for line, pattern in zip(lines, PINNED_NONE_WIN, strict=True):
        assert re.fullmatch(pattern, line), pattern
    assert result.stderr == ""


def test_csv_holds_the_classify_columns_and_folders_when_nothing_fits(
    tmp_path: Path, schema_dsn: str, vlm: ScriptedVlm
) -> None:
    vlm.unsorted = True
    source, results, config = _setup(tmp_path)
    assert _invoke(config, schema_dsn, "--csv").exit_code == 0
    body = [row for row in _report(results) if row["status"] == "classified"]
    assert len(body) == 2
    for row in body:
        assert row["format"] == "unsorted"
        assert row["topic"] == ""
        assert row["needs_review"] == "true"
        assert row["review_reason"] == "unsorted"
        assert row["proposed_output"] == ""  # files.proposed_path is the name node's (CLI-005.D1)
    by_hash = {row["source_hash"]: row for row in body}
    alpha = by_hash[sha256((source / "alpha.png").read_bytes()).hexdigest()]
    bravo = by_hash[sha256((source / "bravo.png").read_bytes()).hexdigest()]
    assert (alpha["branch"], alpha["proposed_folder"]) == ("safe", "Unsorted")
    assert (bravo["branch"], bravo["proposed_folder"]) == ("nsfw", "Adult/Unsorted")
    skipped = next(row for row in _report(results) if row["status"] == "skipped")
    for column in COLUMNS[COLUMNS.index("proposed_output") :]:
        assert skipped[column] == ""
    with psycopg.connect(schema_dsn) as conn:  # CLI-005.D1: the folder is computed, not stored
        stored = conn.execute("select count(*) from files where proposed_path is not null")
        assert stored.fetchone()[0] == 0


def _expected_folder(conn: psycopg.Connection, row: dict[str, str]) -> str:
    """The folder from the categories table alone, independent of the CLI's resolver."""
    cats = {
        (axis, name): (cid, folder, parent)
        for cid, axis, name, folder, parent in conn.execute(
            "select id, axis, name, folder, parent_id from categories"
        )
    }
    by_id = {cid: (folder, parent) for cid, folder, parent in cats.values()}
    parts: list[str] = []
    if row["format"] == "unsorted":
        parts = ["Unsorted"]
    else:
        chain: list[str] = []
        parent = cats[("topic", row["topic"])][0] if row["topic"] else None
        while parent is not None:
            folder, parent = by_id[parent]
            chain.insert(0, folder)
        parts = [*(chain or ["General"]), cats[("format", row["format"])][1]]
    if row["branch"] == "nsfw":
        parts.insert(0, "Adult")
    return "/".join(parts)


def test_csv_folders_match_the_ledger_when_every_file_wins(tmp_path: Path, schema_dsn: str) -> None:
    _, results, config = _setup(tmp_path)
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 0, result.output
    assert "classified: 2" in result.stdout
    assert "classify errors: 0" in result.stdout
    body = [row for row in _report(results) if row["status"] == "classified"]
    with psycopg.connect(schema_dsn) as conn:
        ledger = {
            h: rest
            for h, *rest in conn.execute(
                "select source_hash, format, topic, branch, needs_review from files"
                " where status = 'classified'"
            )
        }
        assert len(ledger) == len(body) == 2
        for row in body:
            fmt, topic, branch, review = ledger[row["source_hash"]]
            assert (row["format"], row["topic"] or None, row["branch"]) == (fmt, topic, branch)
            assert row["needs_review"] == str(review).lower()
            assert row["proposed_folder"] == _expected_folder(conn, row)
            assert row["proposed_folder"] != ""


def test_a_working_copy_that_cannot_be_read_is_one_fixed_reason_line(
    tmp_path: Path, schema_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, results, config = _setup(tmp_path)
    target = sha256((source / "bravo.png").read_bytes()).hexdigest()
    real = classify_node.open_working_frames

    def failing(work: Path, source_hash: str, ext: str) -> Image.Image:
        if source_hash == target:
            raise classify_node.WorkingCopyUnreadable
        return real(work, source_hash, ext)

    monkeypatch.setattr(classify_node, "open_working_frames", failing)
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 0, result.output
    assert "classified: 1" in result.stdout
    assert "classify errors: 1" in result.stdout
    assert "classify error, classify_working_copy_unreadable: 1" in result.stdout
    assert result.stdout.count("classify error, ") == 1
    bad = next(row for row in _report(results) if row["source_hash"] == target)
    assert bad["status"] == "error"
    assert bad["proposed_folder"] == ""


def test_a_classify_pre_flight_failure_exits_2_after_sanitize_committed(
    tmp_path: Path, schema_dsn: str
) -> None:
    """A setting the classify node can't work with is a fixed-text exit 2 (CLS-002.D9)."""
    _, results, config = _setup(tmp_path)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["nsfw"]["mode"] = "separate"  # not supported before M7
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 2, result.output
    assert isinstance(result.exception, SystemExit)
    assert result.stderr.startswith("error: ")
    assert "nsfw.mode" in result.stderr
    assert "Traceback" not in result.output
    assert not (results / "reports").exists()
    with psycopg.connect(schema_dsn) as conn:
        statuses = {row[0] for row in conn.execute("select status from files")}
    assert "sanitized" in statuses  # the node rolled back; earlier nodes' work stays
    assert "classified" not in statuses


def test_a_folder_that_cannot_be_built_exits_2_and_a_rerun_rebuilds_the_report(
    tmp_path: Path, schema_dsn: str
) -> None:
    _, results, config = _setup(tmp_path)
    data = yaml.safe_load(config.read_text(encoding="utf-8"))
    data["folders"]["layout"] = "{format}/{topic}"  # unsupported (FOP-002.D1)
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 2, result.output
    assert result.stderr == f"error: {REPORT_FOLDER_FAILED}\n"
    assert "classified: 2" in result.stdout  # run committed: the ledger is written
    assert not (results / "reports").exists()
    data["folders"]["layout"] = "{topic}/{format}"
    config.write_text(yaml.safe_dump(data), encoding="utf-8")
    again = _invoke(config, schema_dsn, "--csv")
    assert again.exit_code == 0, again.output
    assert all(row["proposed_folder"] for row in _report(results) if row["status"] == "classified")


def test_classify_output_carries_no_planted_name_or_category(
    tmp_path: Path, schema_dsn: str
) -> None:
    source, results, config = _setup(tmp_path)
    _plant(source)
    result = _invoke(config, schema_dsn, "--csv")
    assert result.exit_code == 0, result.output
    _assert_clean(result)
    with psycopg.connect(schema_dsn) as conn:
        names = {name for (name,) in conn.execute("select name from categories")}
        names |= {f for (f,) in conn.execute("select folder from categories")}
    fixed = re.compile(r"[a-z -]+(, \w+)?: \d+")
    free = "\n".join(  # the fixed labels may repeat a category's word (`unsorted`); no other line
        line for line in result.stdout.splitlines() if not fixed.fullmatch(line)
    )
    for name in names:
        assert name not in free, "a category name reached the console"
    assert "/source" not in result.stdout
    assert "classified: 3" in result.stdout
