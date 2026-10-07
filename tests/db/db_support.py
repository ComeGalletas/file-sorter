"""TST-002.1: the one place that checks `DB_DSN` for the db tier."""

import os

import pytest


def require_db_dsn() -> str:
    dsn = os.environ.get("DB_DSN")
    if not dsn:
        pytest.fail(
            "DB_DSN is not set: the db tier needs the throwaway Postgres of the `test` "
            "compose profile. Run it with `make test` (or "
            "`docker compose --profile test run --rm test pytest tests/db`).",
            pytrace=False,
        )
    return dsn
