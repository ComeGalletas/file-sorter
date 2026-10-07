"""TST-002.4: gate 1's decision logic, on plain numbers (no db, no images)."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_1.py"
spec = importlib.util.spec_from_file_location("gate_1", SCRIPT)
assert spec and spec.loader
gate_1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_1)


def _judge(**over: int):
    args = {
        "new": 0,
        "skipped_known": 7,
        "skipped_unreadable": 2,
        "duplicate": 1,
        "rows_before": 8,
        "rows_after": 8,
    }
    return gate_1.judge(**{**args, **over})


def test_clean_rerun_passes() -> None:
    verdict = _judge()
    assert verdict.passed
    text = "\n".join(verdict.lines)
    assert "100.0%" in text and "new ledger rows: 0" in text and "PASS" in text


def test_any_new_file_on_rerun_fails() -> None:
    assert not _judge(new=1).passed


def test_new_ledger_row_fails_even_when_buckets_look_clean() -> None:
    assert not _judge(rows_after=9).passed


def test_lost_ledger_row_fails() -> None:
    assert not _judge(rows_after=7).passed


def test_empty_tree_fails() -> None:
    empty = {"skipped_known": 0, "skipped_unreadable": 0, "duplicate": 0}
    assert not _judge(**empty, rows_before=0, rows_after=0).passed


def test_output_carries_no_counts() -> None:
    """DOC-005.D1: neither a passing nor a failing run prints a count of the files."""
    odd = {"skipped_known": 37, "skipped_unreadable": 23, "duplicate": 13}
    for verdict in (
        _judge(**odd, rows_before=74, rows_after=74),
        _judge(**odd, new=41, rows_before=74, rows_after=115),
    ):
        text = " ".join(verdict.lines)
        for number in ("37", "23", "13", "41", "74", "115", "60", "101"):
            assert number not in text


def test_share_is_a_percentage_of_total() -> None:
    assert gate_1.skipped_share(1, 3, 0, 0) == pytest.approx(75.0)
    assert gate_1.skipped_share(0, 0, 0, 0) == 0.0


def test_missing_dsn_and_fixtures_are_named(tmp_path: Path) -> None:
    with pytest.raises(gate_1.GateSetupError, match="DB_DSN"):
        gate_1.check_prerequisites(None, tmp_path)
    with pytest.raises(gate_1.GateSetupError, match=r"fixtures/images/ is missing"):
        gate_1.check_prerequisites("postgresql://x", tmp_path / "nope")
    with pytest.raises(gate_1.GateSetupError, match="empty"):
        gate_1.check_prerequisites("postgresql://x", tmp_path)
