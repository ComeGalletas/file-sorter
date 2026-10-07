"""TST-003.1: the shared private-schema fixture (tests/integration/conftest.py).

The module's schema is private, at the single Alembic head, and holds the `files` it reads;
`empty_ledger` empties it between tests; `migrated_schema` gives each caller its own schema
and drops it on exit, so no test ever truncates a schema it shares.
"""

import psycopg
import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import INI, migrated_schema

INSERT = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
    "values (%s, %s, '/source/x', now(), 'png')"
)
# Set by the first test of the ordered pair; the second fails unless it ran first.
_WRITTEN: dict[str, str] = {}
FIRST_HASH = "c" * 64


def _schema_exists(name: str) -> bool:
    with psycopg.connect(require_db_dsn()) as conn:
        row = conn.execute(
            "select count(*) from information_schema.schemata where schema_name = %s", (name,)
        ).fetchone()
    return row == (1,)


def test_schema_is_private_and_at_the_single_head(schema_dsn: str) -> None:
    heads = ScriptDirectory.from_config(Config(str(INI))).get_heads()
    assert len(heads) == 1
    with psycopg.connect(schema_dsn) as conn:
        schema = conn.execute("select current_schema()").fetchone()[0]
        owner = conn.execute(
            "select n.nspname from pg_class c join pg_namespace n on n.oid = c.relnamespace "
            "where c.oid = 'files'::regclass"
        ).fetchone()[0]
        version = conn.execute("select version_num from alembic_version").fetchall()
    assert schema.startswith("module_"), "the module's search_path must lead to its own schema"
    assert owner == schema, "`files` must resolve to the module's schema, never a shared one"
    assert version == [(heads[0],)]


@pytest.mark.usefixtures("empty_ledger")
def test_pair_1_commits_a_row(schema_dsn: str) -> None:
    with psycopg.connect(schema_dsn) as conn:
        conn.execute(INSERT, (FIRST_HASH, FIRST_HASH[:8]))
    with psycopg.connect(schema_dsn) as other:
        assert other.execute("select count(*) from files").fetchone() == (1,)
    _WRITTEN["hash"] = FIRST_HASH


@pytest.mark.usefixtures("empty_ledger")
def test_pair_2_starts_on_an_empty_ledger(schema_dsn: str) -> None:
    assert _WRITTEN.get("hash") == FIRST_HASH, (
        "test_pair_1_commits_a_row did not run first in this session: this test proves "
        "nothing alone. Run the whole module, not one test."
    )
    with psycopg.connect(schema_dsn) as conn:
        assert conn.execute("select count(*) from files").fetchone() == (0,)


def test_each_call_gets_its_own_schema_dropped_on_exit() -> None:
    db_dsn = require_db_dsn()
    with migrated_schema(db_dsn) as first, migrated_schema(db_dsn) as second:
        with psycopg.connect(first) as a, psycopg.connect(second) as b:
            name_a = a.execute("select current_schema()").fetchone()[0]
            name_b = b.execute("select current_schema()").fetchone()[0]
            a.execute(INSERT, ("d" * 64, "dddddddd"))
            a.commit()
            assert b.execute("select count(*) from files").fetchone() == (0,)
        assert name_a != name_b
        assert _schema_exists(name_a) and _schema_exists(name_b)
    assert not _schema_exists(name_a)
    assert not _schema_exists(name_b)
