"""DB-004.1 acceptance: migration 0004 adds `files.nsfw_level`, checked against four levels.

Isolated like test_categories_migration.py: a throwaway schema per test, dropped with `cascade`.
Every value is synthetic.
"""

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
from tests.db.db_support import require_db_dsn

INI = Path(__file__).resolve().parents[3] / "classifier" / "db" / "alembic.ini"
HASH = "a" * 64
LEVELS = ("safe", "suggestive", "nudity", "explicit")
INSERT_FILE = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
    "values (%s, 'aaaaaaaa', '/source/x', now(), 'png')"
)


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"mig_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(require_db_dsn(), autocommit=True) as conn:
        conn.execute(f'create schema "{name}"')
        try:
            yield name
        finally:
            conn.execute(f'drop schema "{name}" cascade')


@pytest.fixture
def alembic_cfg(schema: str) -> Config:
    url = make_url(to_sqlalchemy_url(require_db_dsn())).update_query_dict(
        {"options": f"-c search_path={schema},public"}
    )
    cfg = Config(str(INI))
    # configparser interpolation: a literal % must be doubled.
    rendered = url.render_as_string(hide_password=False).replace("%", "%%")
    cfg.set_main_option("sqlalchemy.url", rendered)
    return cfg


@pytest.fixture
def conn(alembic_cfg: Config, schema: str) -> Iterator[psycopg.Connection]:
    """An autocommit connection on a schema at head."""
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        yield c


def _rows(schema: str, sql: str) -> list[tuple]:
    with psycopg.connect(require_db_dsn()) as c:
        c.execute(f'set search_path to "{schema}", public')
        return c.execute(sql).fetchall()


def _nsfw_level_column(schema: str) -> list[tuple]:
    return _rows(
        schema,
        "select data_type, is_nullable = 'YES', column_default from information_schema.columns "
        f"where table_schema = '{schema}' and table_name = 'files' and column_name = 'nsfw_level'",
    )


def _check_names(schema: str) -> list[str]:
    return [
        name
        for (name,) in _rows(
            schema,
            "select conname from pg_constraint "
            f"where conrelid = '\"{schema}\".files'::regclass and contype = 'c' order by 1",
        )
    ]


def test_0004_is_the_single_head_after_0003(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert len(script.get_heads()) == 1  # later migrations extend the chain
    assert script.get_revision("0004").down_revision == "0003"


def test_upgrade_adds_a_nullable_text_column_and_the_check(
    alembic_cfg: Config, schema: str
) -> None:
    command.upgrade(alembic_cfg, "0003")
    assert _nsfw_level_column(schema) == []
    assert "files_nsfw_level" not in _check_names(schema)

    command.upgrade(alembic_cfg, "0004")
    assert _nsfw_level_column(schema) == [("text", True, None)]  # no default (DB-004.D1)
    assert "files_nsfw_level" in _check_names(schema)
    assert _rows(schema, "select version_num from alembic_version") == [("0004",)]


def test_the_check_accepts_the_four_levels_and_null(conn: psycopg.Connection) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    for level in (*LEVELS, None):
        conn.execute("update files set nsfw_level = %s", (level,))
        assert conn.execute("select nsfw_level from files").fetchone() == (level,)


@pytest.mark.parametrize("level", ["Safe", "SAFE", "nsfw", "unknown", "", " safe", "explicit "])
def test_the_check_refuses_anything_else(conn: psycopg.Connection, level: str) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update files set nsfw_level = %s", (level,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into files (source_hash, short_hash, source_path, source_mtime, ext, "
            "nsfw_level) values (%s, 'bbbbbbbb', '/source/y', now(), 'png', %s)",
            ("b" * 64, level),
        )
    assert conn.execute("select nsfw_level from files").fetchall() == [(None,)]


def test_a_new_row_reads_null(conn: psycopg.Connection) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    assert conn.execute("select nsfw_level from files").fetchone() == (None,)


def test_no_backfill_a_row_from_before_the_upgrade_stays_null(
    alembic_cfg: Config, schema: str
) -> None:
    """DB-004.D1: a row classified before 0004 reads null, and its other columns are untouched."""
    command.upgrade(alembic_cfg, "0003")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        c.execute(INSERT_FILE, (HASH,))
        c.execute("update files set format = 'qorvex', nsfw_score = 0.25")

    command.upgrade(alembic_cfg, "head")
    assert _rows(schema, "select source_hash, format, nsfw_score, nsfw_level from files") == [
        (HASH, "qorvex", 0.25, None)
    ]


def test_nsfw_score_is_untouched(alembic_cfg: Config, schema: str) -> None:
    """CLS-004.D5: `nsfw_score` stays a nullable float (values: see the upgrade tests)."""
    command.upgrade(alembic_cfg, "head")
    assert _rows(
        schema,
        "select data_type, is_nullable = 'YES' from information_schema.columns "
        f"where table_schema = '{schema}' and table_name = 'files' and column_name = 'nsfw_score'",
    ) == [("double precision", True)]  # 0001's Float, unchanged
    assert _check_names(schema) == ["files_nsfw_level", "files_review_reason"]


def test_downgrade_to_0003_drops_only_the_column_and_back(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        c.execute(INSERT_FILE, (HASH,))
        c.execute(
            "update files set format = 'qorvex', nsfw_score = 0.5, nsfw_level = 'safe', "
            "image_vec = %s::vector",
            ("[" + ",".join(["0.5"] * 1152) + "]",),
        )

    command.downgrade(alembic_cfg, "0003")
    assert _nsfw_level_column(schema) == []
    assert "files_nsfw_level" not in _check_names(schema)
    # Only what 0004 added is gone: the row, its other columns and 0003's tables survive.
    assert _rows(
        schema, "select source_hash, format, nsfw_score, vector_dims(image_vec) from files"
    ) == [(HASH, "qorvex", 0.5, 1152)]
    assert _rows(schema, "select count(*) > 0 from categories") == [(True,)]
    assert _rows(schema, "select version_num from alembic_version") == [("0003",)]

    command.upgrade(alembic_cfg, "head")
    assert _nsfw_level_column(schema) == [("text", True, None)]
    assert _rows(schema, "select nsfw_level from files") == [(None,)]  # the old value is gone
