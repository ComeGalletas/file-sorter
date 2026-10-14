"""CLI-005.1: the classify columns of the dry-run CSV, with no database."""

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from classifier.cli import app
from classifier.cli.dry_run_report import (
    COLUMNS,
    REPORT_FOLDER_FAILED,
    REPORT_WRITE_FAILED,
    LedgerRow,
    ReportFolderError,
    ReportWriteError,
    folder_resolver,
    write_csv,
)
from classifier.config import Config
from tests.unit.cli.test_dry_run_config_errors import _config_file, _fake_run_result, _FakeConn

STAMP = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
REAL_CONFIG = Path(__file__).resolve().parents[3] / "config.yaml"
PLANTED = "Qorvex-secret"  # made up; it may reach the CSV only


def _classified(**kw: object) -> LedgerRow:
    base: dict[str, object] = {
        "source_hash": "c" * 64,
        "short_hash": "c" * 8,
        "source_path": f"/source/{PLANTED}.png",
        "sanitized_name": f"{PLANTED}-stem",
        "status": "classified",
        "reason": None,
        "format": "Zhyndelfmt",
        "topic": f"{PLANTED}-topic",
        "branch": "safe",
        "needs_review": False,
    }
    return LedgerRow(**{**base, **kw})  # type: ignore[arg-type]


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_classify_columns_follow_proposed_output(tmp_path: Path) -> None:
    assert COLUMNS[COLUMNS.index("proposed_output") + 1 :] == (
        "format",
        "topic",
        "branch",
        "needs_review",
        "review_reason",
        "proposed_folder",
    )
    rows = [
        _classified(),
        _classified(format="unsorted", topic=None, needs_review=True, review_reason="unsorted"),
        LedgerRow("d" * 64, "d" * 8, "/source/y.png", None, "queued", None),
    ]
    written = _read(write_csv(str(tmp_path), STAMP, rows, lambda row: "F/" + row.short_hash))
    assert [r["format"] for r in written] == ["Zhyndelfmt", "unsorted", ""]
    assert [r["topic"] for r in written] == [PLANTED + "-topic", "", ""]
    assert [r["branch"] for r in written] == ["safe", "safe", ""]
    assert [r["needs_review"] for r in written] == ["false", "true", ""]
    assert [r["review_reason"] for r in written] == ["", "unsorted", ""]
    assert [r["proposed_folder"] for r in written] == ["F/cccccccc", "F/cccccccc", "F/dddddddd"]
    assert all(r["proposed_output"] == "" for r in written)


def test_without_a_resolver_proposed_folder_is_empty(tmp_path: Path) -> None:
    written = _read(write_csv(str(tmp_path), STAMP, [_classified()]))
    assert [r["proposed_folder"] for r in written] == [""]


def test_repr_and_str_hide_every_path_name_and_category() -> None:
    row = _classified()
    for text in (repr(row), str(row)):
        assert PLANTED not in text
        assert "Zhyndelfmt" not in text
        assert "/source" not in text
    assert "cccccccc" in repr(row)  # hashes stay visible


def test_a_non_utf8_name_is_written_back_as_its_original_bytes(tmp_path: Path) -> None:
    raw = b"/source/caf\xe9.png"  # a latin-1 name, held as a surrogate escape
    row = _classified(source_path=raw.decode("utf-8", errors="surrogateescape"))
    assert raw in write_csv(str(tmp_path), STAMP, [row]).read_bytes()


def test_a_lone_surrogate_outside_the_escape_range_is_a_fixed_error(tmp_path: Path) -> None:
    row = _classified(source_path="/source/\ud800.png")
    with pytest.raises(ReportWriteError) as caught:
        write_csv(str(tmp_path), STAMP, [row])
    assert str(caught.value) == REPORT_WRITE_FAILED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_a_folder_problem_leaves_no_report_and_no_value_in_the_error(tmp_path: Path) -> None:
    def broken(row: LedgerRow) -> str:
        raise ReportFolderError(REPORT_FOLDER_FAILED)

    with pytest.raises(ReportFolderError) as caught:
        write_csv(str(tmp_path), STAMP, [_classified()], broken)
    assert not (tmp_path / "reports").exists()
    assert str(caught.value) == REPORT_FOLDER_FAILED
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


# --- CLI-005.1.4: no partial report; the CLI-level surrogate case; the resolver ------------


def test_an_unencodable_row_leaves_no_report_file_at_all(tmp_path: Path) -> None:
    rows = [_classified(), _classified(source_path="/source/\ud800.png")]
    with pytest.raises(ReportWriteError):
        write_csv(str(tmp_path), STAMP, rows)
    assert not (tmp_path / "reports").exists()  # encoded in memory first: not even a header
    (tmp_path / "reports").mkdir()
    with pytest.raises(ReportWriteError):
        write_csv(str(tmp_path), STAMP, rows)
    assert list((tmp_path / "reports").iterdir()) == []


def test_a_write_failure_after_the_file_was_created_removes_only_that_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = write_csv(str(tmp_path), STAMP, [_classified()])
    real_open = Path.open

    class Failing:
        def __enter__(self) -> "Failing":
            return self

        def __exit__(self, *exc: object) -> bool:
            return False

        def write(self, data: bytes) -> int:
            raise OSError(28, "no space", "/source/Qorvex-secret")

    def opening(self: Path, mode: str = "r", *args: object, **kwargs: object):
        handle = real_open(self, mode, *args, **kwargs)  # type: ignore[arg-type]
        if "x" in mode:
            handle.close()
            return Failing()  # the file exists now, as the exclusive open created it
        return handle

    monkeypatch.setattr(Path, "open", opening)
    with pytest.raises(ReportWriteError) as caught:
        write_csv(str(tmp_path), STAMP, [_classified()])
    assert PLANTED not in str(caught.value)
    assert [p.name for p in (tmp_path / "reports").iterdir()] == [first.name]


def test_the_cli_reports_a_lone_surrogate_path_with_fixed_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config_file(tmp_path)
    row = _classified(source_path="/source/Qorvex-\ud800-secret.png")
    monkeypatch.setattr("classifier.cli.psycopg.connect", lambda dsn: _FakeConn())
    monkeypatch.setattr("classifier.cli.dry_run_report.rows_under_root", lambda c, root: [row])
    monkeypatch.setattr("classifier.cli.dry_run_report.folder_resolver", lambda c, cfg: None)
    monkeypatch.setattr("classifier.cli.run", lambda cfg, dry_run: _fake_run_result())
    result = CliRunner().invoke(
        app, ["dry-run", "--csv", "--config", str(config)], env={"DB_DSN": "postgresql://u:p@db/x"}
    )
    assert result.exit_code == 2, result.output
    assert result.stderr == f"error: {REPORT_WRITE_FAILED}\n"
    for stream in (result.stdout, result.stderr):
        assert PLANTED not in stream
        assert "\ud800" not in stream
        assert "ud800" not in stream
    assert "Traceback" not in result.output
    assert not (tmp_path / "res" / "reports").exists()


class _Cursor:
    def __init__(self, rows: list[tuple]) -> None:
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class _CategoriesConn:
    """Answers the categories query: (id, axis, name, folder, min_score, branch, parent_id)."""

    def execute(self, sql: str) -> _Cursor:
        return _Cursor(
            [
                (1, "format", "Zhyndelfmt", "Zhyndel", None, "any", None),
                (2, "format", "unsorted", "Unsorted", None, "any", None),
                (3, "topic", "Qorvex", "Qorvex", None, "any", None),
            ]
        )


def test_an_unknown_format_or_removed_topic_gets_an_empty_proposed_folder() -> None:
    """DB-003.D1: the ledger keeps the old text; the report leaves the folder blank."""
    config = Config.model_validate(yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8")))
    folder_of = folder_resolver(_CategoriesConn(), config)  # type: ignore[arg-type]
    assert folder_of(_classified(format="Zhyndelfmt", topic="Qorvex")) == "Qorvex/Zhyndel"
    assert folder_of(_classified(format="Zhyndelfmt", topic=None)) != ""
    assert folder_of(_classified(format="Removedfmt", topic=None)) == ""
    assert folder_of(_classified(format="Zhyndelfmt", topic="Removedtopic")) == ""
    assert folder_of(_classified(status="queued")) == ""
