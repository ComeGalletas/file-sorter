"""TST-002.1 acceptance: one migrated database per session, a rollback per test."""

import psycopg
import pytest

from tests.db.db_support import require_db_dsn

INSERT = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
    "values (%s, %s, '/source/x', now(), 'png')"
)
# Set by the first test of the ordered pair; the second fails unless it ran first.
_WRITTEN: dict[str, str] = {}
FIRST_HASH = "f" * 64


def test_session_is_migrated_to_the_single_head(db: psycopg.Connection) -> None:
    assert db.execute("select to_regclass('files') is not null").fetchone() == (True,)
    assert db.execute("select version_num from alembic_version").fetchall() == [("0001",)]


def test_rollback_inside_one_test(migrated_db: str) -> None:
    """A write is visible on its own connection, gone after rollback, with no second test."""
    with psycopg.connect(migrated_db) as conn:
        conn.execute(INSERT, ("e" * 64, "eeeeeeee"))
        assert conn.execute(
            "select count(*) from files where short_hash = 'eeeeeeee'"
        ).fetchone() == (1,)
        conn.rollback()
    with psycopg.connect(migrated_db) as other:
        assert other.execute(
            "select count(*) from files where short_hash = 'eeeeeeee'"
        ).fetchone() == (0,)


def test_pair_1_writes_a_row(db: psycopg.Connection) -> None:
    db.execute(INSERT, (FIRST_HASH, FIRST_HASH[:8]))
    assert db.execute(
        "select count(*) from files where source_hash = %s", (FIRST_HASH,)
    ).fetchone() == (1,)
    _WRITTEN["hash"] = FIRST_HASH


def test_pair_2_does_not_see_it(db: psycopg.Connection) -> None:
    assert _WRITTEN.get("hash") == FIRST_HASH, (
        "test_pair_1_writes_a_row did not run first in this session: this test proves "
        "nothing alone. Run the whole module, not one test."
    )
    assert db.execute(
        "select count(*) from files where source_hash = %s", (FIRST_HASH,)
    ).fetchone() == (0,)


def test_missing_dsn_fails_naming_the_prerequisite(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("DB_DSN", raising=False)
    with pytest.raises(pytest.fail.Exception) as exc:
        require_db_dsn()
    assert "DB_DSN" in str(exc.value)
    assert "`test`" in str(exc.value)
    assert "compose profile" in str(exc.value)
