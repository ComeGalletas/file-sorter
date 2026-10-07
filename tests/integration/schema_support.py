"""TST-003.1: a private, migrated schema for tests whose code under test commits (PIPE-001.1).

`run` opens its own connection and commits once per node (PIPE-001.D3), so the shared `db`
fixture (a rolled-back transaction in the session schema) can't hold it, and truncating the
shared schema would make other db tests order-dependent. `migrated_schema` builds a
uuid-named schema, migrates it once, and drops it with `cascade` on exit, the way
tests/db/ledger/test_files_migration.py does.

Integration tests take it through the `schema_dsn` and `empty_ledger` fixtures in
tests/integration/conftest.py. Call the context manager directly only outside pytest's
fixtures, as scripts/gate_1.py does.
"""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config as AlembicConfig

INI = Path(__file__).resolve().parents[2] / "classifier" / "db" / "alembic.ini"


@contextmanager
def migrated_schema(db_dsn: str) -> Iterator[str]:
    """Yield a DSN whose `search_path` is a fresh schema migrated to Alembic head."""
    schema = f"module_{uuid.uuid4().hex[:12]}"
    options = quote(f"-c search_path={schema},public", safe="")
    dsn = f"{db_dsn}{'&' if '?' in db_dsn else '?'}options={options}"
    with psycopg.connect(db_dsn, autocommit=True) as admin:
        admin.execute("create extension if not exists vector schema public")
        admin.execute(f'create schema "{schema}"')
        try:
            # env.py takes the DSN through load_config, where `DB_DSN` wins (CFG-001.D2).
            with pytest.MonkeyPatch.context() as patch:
                patch.setenv("DB_DSN", dsn)
                command.upgrade(AlembicConfig(str(INI)), "head")
            yield dsn
        finally:
            admin.execute(f'drop schema "{schema}" cascade')
