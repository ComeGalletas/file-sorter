"""TST-002.1: db-tier fixtures. One migrated database per session, a rollback per test.

`db_dsn` owns the `DB_DSN` check (CLAUDE.md §3: never skip, name the missing prerequisite).
`migrated_db` runs `alembic upgrade head` once. `db` hands each test a connection whose
transaction is always rolled back, so a test's writes never reach the next one. A test that
must commit (DDL, migrations) isolates itself in its own schema instead, as
tests/db/ledger/test_files_migration.py does.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from tests.db.db_support import require_db_dsn

INI = Path(__file__).resolve().parents[2] / "classifier" / "db" / "alembic.ini"


@pytest.fixture(scope="session")
def db_dsn() -> str:
    return require_db_dsn()


@pytest.fixture(scope="session")
def migrated_db(db_dsn: str) -> Iterator[str]:
    """The test database at Alembic head, migrated once per session. Yields its DSN.

    The migration runs in its own schema, reached through `options=-c search_path=...`
    in the yielded DSN, so `public` keeps only the extension. That keeps PR #30's
    migration test (its own schema, `search_path = <schema>, public`) from seeing this
    session's `files` table or enum, whatever order the tests run in.
    """
    schema = f"session_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(db_dsn, autocommit=True) as admin:
        # Created in public first, so the migration's `if not exists` is a no-op.
        admin.execute("create extension if not exists vector schema public")
        admin.execute(f'create schema "{schema}"')
        try:
            options = quote(f"-c search_path={schema},public", safe="")
            sep = "&" if "?" in db_dsn else "?"
            dsn = f"{db_dsn}{sep}options={options}"
            # env.py takes the DSN through load_config, where `DB_DSN` wins (CFG-001.D2).
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("DB_DSN", dsn)
                command.upgrade(Config(str(INI)), "head")
            yield dsn
        finally:
            admin.execute(f'drop schema "{schema}" cascade')


@pytest.fixture
def db(migrated_db: str) -> Iterator[psycopg.Connection]:
    """A connection inside an outer transaction that is rolled back at teardown."""
    with psycopg.connect(migrated_db) as conn:
        try:
            yield conn
        finally:
            conn.rollback()
