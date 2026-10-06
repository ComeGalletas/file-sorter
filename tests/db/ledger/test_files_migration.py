"""DB-001.1 acceptance: `alembic upgrade head` builds the `files` ledger on `db-test`.

Isolation (lead note, TST-002.1): everything runs in a throwaway schema created for this
test (`search_path = <schema>, public`), so the enum, `files` and `alembic_version` never
touch the shared database's own state. The schema is dropped with `cascade` at the end, on
success or failure, so the database is left exactly as found.
"""

import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy.engine import make_url

from classifier.db.url import to_sqlalchemy_url

INI = Path(__file__).resolve().parents[3] / "classifier" / "db" / "alembic.ini"
STATUSES = [
    "queued", "sanitized", "classified", "captioned", "resolved", "named",
    "proposed", "filed", "skipped", "error", "deleted",
]  # fmt: skip
INGEST_COLUMNS = {
    "source_hash", "short_hash", "source_path", "duplicate_paths", "source_mtime", "ext",
    "status", "needs_review", "created_at", "updated_at",
}  # fmt: skip
LATER_COLUMNS = {
    "branch", "nsfw_score", "animated", "format", "topic", "format_scores", "topic_scores",
    "caption", "prompt_version", "reference_id", "template", "proposed_path", "output_path",
    "output_hash", "review_reason", "has_sensitive_text", "error",
}  # fmt: skip


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"mig_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(os.environ["DB_DSN"], autocommit=True) as conn:
        conn.execute(f'create schema "{name}"')
        try:
            yield name
        finally:
            conn.execute(f'drop schema "{name}" cascade')


@pytest.fixture
def alembic_cfg(schema: str) -> Config:
    url = make_url(to_sqlalchemy_url(os.environ["DB_DSN"])).update_query_dict(
        {"options": f"-c search_path={schema},public"}
    )
    cfg = Config(str(INI))
    # configparser interpolation: a literal % must be doubled.
    rendered = url.render_as_string(hide_password=False).replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", rendered)
    return cfg


def _rows(schema: str, sql: str) -> list[tuple]:
    with psycopg.connect(os.environ["DB_DSN"]) as conn:
        conn.execute(f'set search_path to "{schema}", public')
        return conn.execute(sql).fetchall()


def test_single_head(alembic_cfg: Config) -> None:
    assert len(ScriptDirectory.from_config(alembic_cfg).get_heads()) == 1


def test_upgrade_creates_the_ledger(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")

    cols = dict(
        _rows(
            schema,
            "select column_name, is_nullable = 'YES' from information_schema.columns "
            f"where table_schema = '{schema}' and table_name = 'files'",
        )
    )
    assert set(cols) == INGEST_COLUMNS | LATER_COLUMNS
    assert {c for c, nullable in cols.items() if not nullable} == INGEST_COLUMNS

    pk = _rows(
        schema,
        "select a.attname from pg_index i join pg_attribute a "
        "on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
        f"where i.indrelid = '\"{schema}\".files'::regclass and i.indisprimary",
    )
    assert pk == [("source_hash",)]

    enum = _rows(
        schema,
        "select e.enumlabel from pg_enum e join pg_type t on t.oid = e.enumtypid "
        "join pg_namespace n on n.oid = t.typnamespace "
        f"where t.typname = 'file_status' and n.nspname = '{schema}' order by e.enumsortorder",
    )
    assert [label for (label,) in enum] == STATUSES

    index_rows = _rows(schema, f"select indexname from pg_indexes where schemaname = '{schema}'")
    assert {"ix_files_status", "ix_files_short_hash"} <= {name for (name,) in index_rows}

    assert _rows(schema, "select extname from pg_extension where extname = 'vector'")
    assert _rows(schema, "select version_num from alembic_version") == [("0001",)]


def test_defaults_and_checks(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")
    insert = (
        "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
        "values (repeat('a', 64), 'aaaaaaaa', '/source/x', now(), 'png')"
    )
    with psycopg.connect(os.environ["DB_DSN"], autocommit=True) as conn:
        conn.execute(f'set search_path to "{schema}", public')
        conn.execute(insert)
        row = conn.execute(
            "select status::text, needs_review, duplicate_paths, created_at is not null, "
            "updated_at is not null from files"
        ).fetchone()
        assert row == ("queued", False, [], True, True)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("update files set review_reason = 'bogus'")
        with pytest.raises(psycopg.errors.InvalidTextRepresentation):
            conn.execute("update files set status = 'bogus'")


def test_downgrade_round_trip(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "base")
    assert _rows(schema, f"select to_regclass('\"{schema}\".files')::text") == [(None,)]
    assert not _rows(
        schema,
        "select 1 from pg_type t join pg_namespace n on n.oid = t.typnamespace "
        f"where t.typname = 'file_status' and n.nspname = '{schema}'",
    )
    command.upgrade(alembic_cfg, "head")
    assert _rows(schema, "select count(*) from files") == [(0,)]


def test_models_match_the_migration(alembic_cfg: Config, schema: str) -> None:
    """No drift: Alembic's autogenerate finds nothing to change between `File` and 0001."""
    from alembic.autogenerate import compare_metadata
    from alembic.migration import MigrationContext
    from sqlalchemy import create_engine

    from classifier.db.models import Base

    command.upgrade(alembic_cfg, "head")
    engine = create_engine(alembic_cfg.get_main_option("sqlalchemy.url").replace("%%", "%"))
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    assert diff == []
