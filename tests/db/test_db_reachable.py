"""RUN-001.4: the test profile's throwaway Postgres is reachable and has pgvector."""

import psycopg

from tests.db.db_support import require_db_dsn


def test_db_answers_and_pgvector_loads(request) -> None:
    assert request.node.get_closest_marker("db") is not None
    with psycopg.connect(require_db_dsn(), connect_timeout=10) as conn:
        assert conn.execute("select 1").fetchone() == (1,)
        conn.execute("create extension if not exists vector")
        dims = conn.execute("select vector_dims('[1,2,3]'::vector)").fetchone()
        assert dims == (3,)
