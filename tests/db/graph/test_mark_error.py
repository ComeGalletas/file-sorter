"""SAN-003.1.4: `mark_error`, the one way a row past `queued` moves to `error` (SAN-003.D2)."""

import psycopg
import pytest

from classifier.graph.errors import mark_error, register_reasons
from classifier.graph.sanitize import REASONS, THUMBNAIL_FAILED

HASH = "b" * 64
OTHER = "c" * 64
FIXED = "qorvex_fixed_reason"  # a synthetic registered reason

INSERT_FILE = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext, status,"
    " original_sanitized) values (%s, %s, '/source/x', now(), 'png', %s, 'zhyndel-stem')"
)
INSERT_LOG = (
    "insert into sanitize_log (source_hash, rule_id, field, before_hash, after_value)"
    " values (%s, 'r1', 'filename', %s, 'after')"
)


def _seed(db: psycopg.Connection, source_hash: str, status: str, logs: int = 2) -> None:
    db.execute(INSERT_FILE, (source_hash, source_hash[:8], status))
    for i in range(logs):
        db.execute(INSERT_LOG, (source_hash, f"{i:064x}"))


def _row(db: psycopg.Connection, source_hash: str) -> tuple:
    return db.execute(
        "select status, error, original_sanitized from files where source_hash = %s",
        (source_hash,),
    ).fetchone()


def _logs(db: psycopg.Connection, source_hash: str) -> int:
    row = db.execute(
        "select count(*) from sanitize_log where source_hash = %s", (source_hash,)
    ).fetchone()
    return int(row[0])


@pytest.fixture(autouse=True)
def _registered() -> None:
    register_reasons([FIXED])


def test_a_sanitized_row_goes_to_error_and_its_log_is_cleared(db: psycopg.Connection) -> None:
    _seed(db, HASH, "sanitized")
    _seed(db, OTHER, "sanitized")
    assert mark_error(db, HASH, FIXED, from_statuses=("sanitized",)) is True
    assert _row(db, HASH) == ("error", FIXED, None)
    assert _logs(db, HASH) == 0
    assert _logs(db, OTHER) == 2  # another row's log is untouched


def test_a_queued_row_works_too(db: psycopg.Connection) -> None:
    _seed(db, HASH, "queued", logs=1)
    assert mark_error(db, HASH, FIXED, from_statuses=("queued", "sanitized")) is True
    assert _row(db, HASH)[:2] == ("error", FIXED)
    assert _logs(db, HASH) == 0


def test_a_row_in_another_status_is_untouched(db: psycopg.Connection) -> None:
    _seed(db, HASH, "sanitized")
    assert mark_error(db, HASH, FIXED, from_statuses=("queued",)) is False
    assert _row(db, HASH) == ("sanitized", None, "zhyndel-stem")
    assert _logs(db, HASH) == 2


def test_an_unknown_row_returns_false(db: psycopg.Connection) -> None:
    assert mark_error(db, HASH, FIXED, from_statuses=("queued",)) is False


def test_a_second_call_is_a_no_op(db: psycopg.Connection) -> None:
    _seed(db, HASH, "sanitized")
    assert mark_error(db, HASH, FIXED, from_statuses=("sanitized",)) is True
    assert mark_error(db, HASH, FIXED, from_statuses=("sanitized",)) is False  # already error


@pytest.mark.parametrize("reason", ["OSError: /source/qorvex/zhyndel.jpg", "", FIXED + " "])
def test_a_reason_no_node_registered_is_refused(db: psycopg.Connection, reason: str) -> None:
    _seed(db, HASH, "sanitized")
    with pytest.raises(ValueError) as raised:
        mark_error(db, HASH, reason, from_statuses=("sanitized",))
    assert "qorvex" not in str(raised.value) and "zhyndel" not in str(raised.value)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
    assert _row(db, HASH)[0] == "sanitized"  # refused before any write
    assert _logs(db, HASH) == 2


def test_every_sanitize_reason_is_accepted(db: psycopg.Connection) -> None:
    # SAN-003.2 added a reason: the registry must follow REASONS, not a copy of it.
    for i, reason in enumerate(REASONS):
        source_hash = f"{i:064x}"
        _seed(db, source_hash, "queued", logs=1)
        assert mark_error(db, source_hash, reason, from_statuses=("queued",)) is True
    assert THUMBNAIL_FAILED in REASONS
