"""Migration 0005: files.review_reason allows nsfw_disagreement (DB-005.1; DB-005.D1)."""

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
INSERT_FILE = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
    "values (%s, 'aaaaaaaa', '/source/x', now(), 'png')"
)
REFUSED = "Downgrade refused: rows with review_reason nsfw_disagreement exist."


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
    cfg.set_main_option(
        "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
    )
    return cfg


def _connect(schema: str) -> psycopg.Connection:
    c = psycopg.connect(require_db_dsn(), autocommit=True)
    c.execute(f'set search_path to "{schema}", public')
    return c


@pytest.fixture
def conn(alembic_cfg: Config, schema: str) -> Iterator[psycopg.Connection]:
    """An autocommit connection on a schema at head."""
    command.upgrade(alembic_cfg, "head")
    with _connect(schema) as c:
        yield c


def test_0005_extends_0004_and_the_chain_has_one_head(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert len(script.get_heads()) == 1
    assert script.get_revision("0005").down_revision == "0004"


@pytest.mark.parametrize("reason", [None, "unsorted", "ambiguous_reference", "nsfw_disagreement"])
def test_the_check_accepts_every_reason_and_null(
    conn: psycopg.Connection, reason: str | None
) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    conn.execute("update files set review_reason = %s", (reason,))
    assert conn.execute("select review_reason from files").fetchone() == (reason,)


@pytest.mark.parametrize("reason", ["bogus", "", "NSFW_DISAGREEMENT", "nsfw_disagreement "])
def test_the_check_still_refuses_an_unknown_reason(conn: psycopg.Connection, reason: str) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update files set review_reason = %s", (reason,))
    assert conn.execute("select review_reason from files").fetchone() == (None,)


def test_the_downgrade_is_refused_while_a_row_holds_the_reason(
    alembic_cfg: Config, schema: str, conn: psycopg.Connection
) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    conn.execute("update files set review_reason = 'nsfw_disagreement'")

    with pytest.raises(Exception) as caught:  # Alembic may wrap; the text must surface
        command.downgrade(alembic_cfg, "0004")
    assert REFUSED in str(caught.value)
    assert HASH not in str(caught.value)
    # Whatever Alembic wraps, the root of the chain is our fixed text and nothing deeper.
    root = caught.value
    while root.__cause__ is not None or root.__context__ is not None:
        root = root.__cause__ or root.__context__
    assert REFUSED in str(root)

    # Nothing changed: same revision, same constraint, row untouched (fresh connection).
    with _connect(schema) as fresh:
        assert fresh.execute("select version_num from alembic_version").fetchall() == [("0005",)]
        assert fresh.execute("select review_reason from files").fetchall() == [
            ("nsfw_disagreement",)
        ]
        fresh.execute("update files set review_reason = 'unsorted'")
        fresh.execute("update files set review_reason = 'nsfw_disagreement'")


def test_the_downgrade_runs_on_an_empty_table_and_restores_the_old_check(
    alembic_cfg: Config, schema: str
) -> None:
    command.upgrade(alembic_cfg, "head")
    command.downgrade(alembic_cfg, "0004")
    with _connect(schema) as c:
        assert c.execute("select version_num from alembic_version").fetchall() == [("0004",)]
        c.execute(INSERT_FILE, (HASH,))
        c.execute("update files set review_reason = 'ambiguous_reference'")
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("update files set review_reason = 'nsfw_disagreement'")

    command.upgrade(alembic_cfg, "head")  # and back
    with _connect(schema) as c:
        c.execute("update files set review_reason = 'nsfw_disagreement'")
        assert c.execute("select review_reason from files").fetchone() == ("nsfw_disagreement",)


def test_the_downgrade_leaves_other_reasons_alone(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")
    with _connect(schema) as c:
        c.execute(INSERT_FILE, (HASH,))
        c.execute("update files set review_reason = 'unsorted'")
    command.downgrade(alembic_cfg, "0004")
    with _connect(schema) as c:
        assert c.execute("select review_reason from files").fetchall() == [("unsorted",)]
