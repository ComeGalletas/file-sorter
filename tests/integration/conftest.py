"""TST-003.1: integration-tier fixtures. A private migrated schema per module.

Code that commits (`run`, `classifier dry-run`) can't use the db tier's rolled-back `db`
fixture, so a module that needs a ledger asks for `schema_dsn`: its own uuid-named schema at
Alembic head, built once per module and dropped with `cascade` at module teardown (see
tests/integration/schema_support.py). A module whose tests each want an empty ledger opts in
with `pytestmark = pytest.mark.usefixtures("empty_ledger")`. Neither fixture is autouse, so a
module that never touches the db never pays for a migration.
"""

from collections.abc import Iterator

import psycopg
import pytest

from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import migrated_schema


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    """A DSN whose `search_path` is this module's private schema, migrated to head."""
    with migrated_schema(require_db_dsn()) as dsn:
        yield dsn


@pytest.fixture
def empty_ledger(schema_dsn: str) -> None:
    """Empty `files` and every table that references it, in this module's private schema.

    `cascade` covers the child tables with a foreign key to `files` (`sanitize_log`, DB-002.D2,
    and any later one); the unqualified name resolves through the module's `search_path`, so a
    shared schema is never touched (TST-003, TST-006.1).
    """
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("truncate files cascade")
