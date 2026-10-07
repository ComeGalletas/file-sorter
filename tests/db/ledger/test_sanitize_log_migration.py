"""DB-002.1 acceptance: migration 0002 adds `sanitize_log` and `files.original_sanitized`.

Isolated like test_files_migration.py: a throwaway schema per test, dropped with `cascade`.
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
HMAC = "0123456789abcdef" * 4
LOG_COLUMNS = {
    "id": False, "source_hash": False, "rule_id": False, "field": False,
    "before_hash": False, "after_value": True, "created_at": False,
}  # fmt: skip
INSERT_FILE = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
    "values (%s, 'aaaaaaaa', '/source/x', now(), 'png')"
)
INSERT_LOG = (
    "insert into sanitize_log (source_hash, rule_id, field, before_hash, after_value) "
    "values (%s, %s, %s, %s, %s)"
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
    """An autocommit connection on a schema at head, with one `files` row (HASH)."""
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        c.execute(INSERT_FILE, (HASH,))
        yield c


def _rows(schema: str, sql: str) -> list[tuple]:
    with psycopg.connect(require_db_dsn()) as c:
        c.execute(f'set search_path to "{schema}", public')
        return c.execute(sql).fetchall()


def _columns(schema: str, table: str) -> dict[str, bool]:
    return dict(
        _rows(
            schema,
            "select column_name, is_nullable = 'YES' from information_schema.columns "
            f"where table_schema = '{schema}' and table_name = '{table}'",
        )
    )


def test_0002_is_the_single_head_after_0001(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert script.get_heads() == ["0002"]
    assert script.get_revision("0002").down_revision == "0001"


def test_upgrade_adds_the_table_and_the_column(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")

    assert _columns(schema, "sanitize_log") == LOG_COLUMNS
    assert _columns(schema, "files")["original_sanitized"] is True

    pk = _rows(
        schema,
        "select a.attname from pg_index i join pg_attribute a "
        "on a.attrelid = i.indrelid and a.attnum = any(i.indkey) "
        f"where i.indrelid = '\"{schema}\".sanitize_log'::regclass and i.indisprimary",
    )
    assert pk == [("id",)]

    # DB-002.D2: the FK to files has no cascade (confdeltype 'a' = no action).
    fks = _rows(
        schema,
        "select conname, confrelid::regclass::text, confdeltype from pg_constraint "
        f"where conrelid = '\"{schema}\".sanitize_log'::regclass and contype = 'f'",
    )
    assert fks == [("fk_sanitize_log_source_hash_files", "files", "a")]

    checks = _rows(
        schema,
        "select conname from pg_constraint "
        f"where conrelid = '\"{schema}\".sanitize_log'::regclass and contype = 'c'",
    )
    assert {name for (name,) in checks} == {
        "sanitize_log_rule_id", "sanitize_log_field", "sanitize_log_before_hash",
    }  # fmt: skip

    index = _rows(
        schema,
        f"select indexdef from pg_indexes where schemaname = '{schema}' "
        "and indexname = 'ix_sanitize_log_source_hash'",
    )
    assert len(index) == 1 and index[0][0].endswith("(source_hash)")

    assert _rows(schema, "select version_num from alembic_version") == [("0002",)]


@pytest.mark.parametrize(
    ("rule_id", "field", "after_value"),
    [
        ("person-names", "filename", "[name]"),
        ("handles_1", "path_segment", "[handle]"),
        ("exif-strip-all", "exif:GPSLatitude", None),  # SAN-001.D12
        ("gps", "exif:XMP-dc:Creator", None),
        ("a" * 64, "filename", ""),
    ],
)
def test_valid_rows_insert(
    conn: psycopg.Connection, rule_id: str, field: str, after_value: str | None
) -> None:
    row = conn.execute(
        INSERT_LOG + " returning id, created_at is not null, after_value",
        (HASH, rule_id, field, HMAC, after_value),
    ).fetchone()
    assert row is not None and row[0] >= 1 and row[1] is True and row[2] == after_value


@pytest.mark.parametrize(
    ("rule_id", "field", "before_hash"),
    [
        # rule_id: SAN-001.1's RuleId pattern
        ("Upper", "filename", HMAC),
        ("-lead", "filename", HMAC),
        ("has space", "filename", HMAC),
        ("", "filename", HMAC),
        # field: DB-002.D1
        ("r", "name", HMAC),
        ("r", "Filename", HMAC),
        ("r", "exif:", HMAC),
        ("r", "EXIF:GPSLatitude", HMAC),
        ("r", "exif:1Tag", HMAC),
        ("r", "exif:Tag Name", HMAC),
        ("r", "exif:" + "T" * 65, HMAC),
        # before_hash: 64 lowercase hex (SAN-001.D5)
        ("r", "filename", HMAC.upper()),
        ("r", "filename", HMAC[:63]),
        ("r", "filename", HMAC[:63] + "g"),
    ],
)
def test_checks_reject_bad_values(
    conn: psycopg.Connection, rule_id: str, field: str, before_hash: str
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(INSERT_LOG, (HASH, rule_id, field, before_hash, None))


@pytest.mark.parametrize(("rule_id", "before_hash"), [("a" * 65, HMAC), ("r", HMAC + "0")])
def test_lengths_are_bounded(conn: psycopg.Connection, rule_id: str, before_hash: str) -> None:
    with pytest.raises(psycopg.errors.StringDataRightTruncation):
        conn.execute(INSERT_LOG, (HASH, rule_id, "filename", before_hash, None))


def test_required_columns_reject_null(conn: psycopg.Connection) -> None:
    for i in range(4):
        values = [HASH, "r", "filename", HMAC]
        values[i] = None
        with pytest.raises(psycopg.errors.NotNullViolation):
            conn.execute(INSERT_LOG, (*values, None))


def test_foreign_key_and_no_cascade(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(INSERT_LOG, ("b" * 64, "r", "filename", HMAC, "[x]"))

    conn.execute(INSERT_LOG, (HASH, "r", "filename", HMAC, "[x]"))
    # DB-002.D2: a referenced files row can't be deleted, and nothing cascades.
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("delete from files where source_hash = %s", (HASH,))
    assert conn.execute("select count(*) from sanitize_log").fetchone() == (1,)


def test_original_sanitized_round_trip(conn: psycopg.Connection) -> None:
    assert conn.execute("select original_sanitized from files").fetchone() == (None,)
    conn.execute("update files set original_sanitized = 'holiday_[name]'")
    assert conn.execute("select original_sanitized from files").fetchone() == ("holiday_[name]",)


def test_downgrade_to_0001_and_back(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        c.execute(INSERT_FILE, (HASH,))
        c.execute(INSERT_LOG, (HASH, "r", "filename", HMAC, "[x]"))

    command.downgrade(alembic_cfg, "0001")
    assert _rows(schema, f"select to_regclass('\"{schema}\".sanitize_log')::text") == [(None,)]
    assert "original_sanitized" not in _columns(schema, "files")
    assert _rows(schema, "select source_hash from files") == [(HASH,)]  # files is untouched
    assert _rows(schema, "select version_num from alembic_version") == [("0001",)]

    command.upgrade(alembic_cfg, "head")
    assert _rows(schema, "select count(*), count(original_sanitized) from files") == [(1, 0)]
    assert _rows(schema, "select count(*) from sanitize_log") == [(0,)]
