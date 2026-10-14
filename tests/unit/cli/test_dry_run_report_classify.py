"""CLI-005.1: the classify columns of the dry-run CSV, with no database."""

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from classifier.cli.dry_run_report import (
    COLUMNS,
    REPORT_FOLDER_FAILED,
    REPORT_WRITE_FAILED,
    LedgerRow,
    ReportFolderError,
    ReportWriteError,
    write_csv,
)

STAMP = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)
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
