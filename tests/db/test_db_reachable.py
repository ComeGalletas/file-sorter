"""RUN-001.4: the test profile's throwaway Postgres is reachable and has pgvector."""

import os

import psycopg


def test_db_answers_and_pgvector_loads(request) -> None:
    assert request.node.get_closest_marker("db") is not None
    with psycopg.connect(os.environ["DB_DSN"], connect_timeout=10) as conn:
        assert conn.execute("select 1").fetchone() == (1,)
        conn.execute("create extension if not exists vector")
        dims = conn.execute("select vector_dims('[1,2,3]'::vector)").fetchone()
        assert dims == (3,)
