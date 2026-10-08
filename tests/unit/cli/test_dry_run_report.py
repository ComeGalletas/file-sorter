"""CLI-002.1.5, CLI-003.1: the prefix match and the CSV writer, with no database."""

import csv
from datetime import UTC, datetime
from pathlib import Path

import pytest

from classifier.cli.dry_run_report import COLUMNS, LedgerRow, prefix_for, write_csv

STAMP = datetime(2026, 10, 6, 12, 0, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("root", "expected"),
    [
        ("/source", "/source/"),
        ("/source/", "/source/"),
        ("/source//", "/source/"),
        ("/data/my_src", "/data/my_src/"),
        ("/data/100%", "/data/100%/"),
    ],
)
def test_prefix_always_ends_in_one_slash_and_keeps_wildcards_literal(
    root: str, expected: str
) -> None:
    assert prefix_for(root) == expected


def test_prefix_does_not_match_a_sibling_with_the_same_start() -> None:
    assert not "/source2/x.png".startswith(prefix_for("/source"))
    assert "/source/x.png".startswith(prefix_for("/source"))


def _rows() -> list[LedgerRow]:
    return [LedgerRow("a" * 64, "a" * 8, "/source/x.png", None, "queued", None)]


def test_two_writes_in_the_same_second_do_not_overwrite(tmp_path: Path) -> None:
    first = write_csv(str(tmp_path), STAMP, _rows())
    second = write_csv(str(tmp_path), STAMP, [])
    third = write_csv(str(tmp_path), STAMP, [])
    assert first.name == "dry-run-20261006T120000Z.csv"
    assert second.name == "dry-run-20261006T120000Z-1.csv"
    assert third.name == "dry-run-20261006T120000Z-2.csv"
    assert "/source/x.png" in first.read_text(encoding="utf-8")  # the first file is intact
    assert second.read_text(encoding="utf-8").strip() == ",".join(COLUMNS)


def test_sanitized_name_sits_beside_source_path_and_is_empty_when_null(tmp_path: Path) -> None:
    """CLI-003.1: ING-001.D2 option A, `files.original_sanitized` beside `source_path`."""
    rows = [
        LedgerRow("a" * 64, "a" * 8, "/source/x.png", "[P]_x", "sanitized", None),
        LedgerRow("b" * 64, "b" * 8, "/source/y.txt", None, "skipped", "unsupported_type"),
    ]
    with write_csv(str(tmp_path), STAMP, rows).open(encoding="utf-8", newline="") as handle:
        written = list(csv.DictReader(handle))
    assert COLUMNS.index("sanitized_name") == COLUMNS.index("source_path") + 1
    assert [(r["source_path"], r["sanitized_name"]) for r in written] == [
        ("/source/x.png", "[P]_x"),
        ("/source/y.txt", ""),
    ]
