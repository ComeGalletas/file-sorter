"""DB-003.1 acceptance: migration 0003 adds `categories`, `category_prompts` and `files.image_vec`.

Isolated like test_sanitize_log_migration.py: a throwaway schema per test, dropped with `cascade`.
Every value is synthetic; the seed is compared with a copy of DESIGN §4.3 written below.
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
CATEGORY_COLUMNS = {
    "id": False, "axis": False, "name": False, "folder": False, "min_score": True,
    "branch": False, "parent_id": True, "created_at": False,
}  # fmt: skip
PROMPT_COLUMNS = {"id": False, "category_id": False, "position": False, "prompt": False}
INSERT_CATEGORY = "insert into categories (axis, name, folder) values (%s, %s, %s) returning id"
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
    """An autocommit connection on a schema at head (the seed is loaded)."""
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
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


def _constraints(schema: str, table: str, kind: str) -> list[tuple]:
    return _rows(
        schema,
        "select conname, confrelid::regclass::text, confdeltype from pg_constraint "
        f"where conrelid = '\"{schema}\".{table}'::regclass and contype = '{kind}' order by 1",
    )


def test_0003_is_the_single_head_after_0002(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert len(script.get_heads()) == 1  # later seed migrations extend the chain (CLS-003.D2)
    assert script.get_revision("0003").down_revision == "0002"


def test_upgrade_adds_the_tables_and_the_column(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")

    assert _columns(schema, "categories") == CATEGORY_COLUMNS
    assert _columns(schema, "category_prompts") == PROMPT_COLUMNS
    assert _columns(schema, "files")["image_vec"] is True

    types = dict(
        _rows(
            schema,
            "select a.attname, format_type(a.atttypid, a.atttypmod) from pg_attribute a "
            f"where a.attrelid in ('\"{schema}\".files'::regclass, "
            f"'\"{schema}\".categories'::regclass) and a.attname in ('image_vec', 'min_score') "
            "and not a.attisdropped",
        )
    )
    assert types == {"image_vec": "vector(1152)", "min_score": "real"}

    assert [c[0] for c in _constraints(schema, "categories", "c")] == [
        "categories_axis", "categories_branch",
    ]  # fmt: skip
    assert _constraints(schema, "categories", "f") == [
        ("fk_categories_parent_id_categories", "categories", "a")
    ]
    # DB-003.1: removing a category takes its prompts with it (confdeltype 'c' = cascade).
    assert _constraints(schema, "category_prompts", "f") == [
        ("fk_category_prompts_category_id_categories", "categories", "c")
    ]
    assert [c[0] for c in _constraints(schema, "categories", "u")] == ["uq_categories_axis_name"]
    assert [c[0] for c in _constraints(schema, "category_prompts", "u")] == [
        "uq_category_prompts_category_position"
    ]
    index = _rows(
        schema,
        f"select indexdef from pg_indexes where schemaname = '{schema}' "
        "and indexname = 'uq_categories_axis_parent_folder'",
    )
    assert len(index) == 1
    assert "UNIQUE" in index[0][0] and "COALESCE(parent_id, 0)" in index[0][0]
    assert "lower(folder)" in index[0][0]

    assert _rows(schema, "select version_num from alembic_version") == [
        (ScriptDirectory.from_config(alembic_cfg).get_current_head(),)
    ]


def test_files_has_no_index_on_image_vec_and_no_fk_from_names(
    alembic_cfg: Config, schema: str
) -> None:
    command.upgrade(alembic_cfg, "head")
    assert _rows(
        schema,
        f"select indexname from pg_indexes where schemaname = '{schema}' "
        "and tablename = 'files' and indexdef ilike '%image_vec%'",
    ) == []
    # DB-003.D1: files.format and files.topic stay plain names.
    assert _constraints(schema, "files", "f") == []


def test_axis_and_branch_checks(conn: psycopg.Connection) -> None:
    for axis in ("Format", "topics", ""):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(INSERT_CATEGORY, (axis, "qorvex", "Qorvex"))
    for branch in ("both", "ANY", ""):
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "insert into categories (axis, name, folder, branch) "
                "values ('topic', 'q', 'Q', %s)",
                (branch,),
            )
    for branch in ("any", "safe", "nsfw"):
        conn.execute(
            "insert into categories (axis, name, folder, branch) values ('topic', %s, %s, %s)",
            (f"q-{branch}", f"Q {branch}", branch),
        )
    row = conn.execute(INSERT_CATEGORY.replace("returning id", "returning branch, min_score"),
                       ("topic", "zhyndel", "Zhyndel")).fetchone()  # fmt: skip
    assert row == ("any", None)


def test_unique_axis_name_but_the_same_name_may_sit_on_both_axes(
    conn: psycopg.Connection,
) -> None:
    conn.execute(INSERT_CATEGORY, ("format", "qorvex", "Qorvex"))
    conn.execute(INSERT_CATEGORY, ("topic", "qorvex", "Qorvex"))  # CLS-001.D10: both axes
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(INSERT_CATEGORY, ("topic", "qorvex", "Other Folder"))


def test_sibling_folders_are_unique_case_insensitively(conn: psycopg.Connection) -> None:
    (first,) = conn.execute(INSERT_CATEGORY, ("topic", "qorvex", "Qorvex")).fetchone()
    with pytest.raises(psycopg.errors.UniqueViolation):  # top-level: parent null counts as 0
        conn.execute(INSERT_CATEGORY, ("topic", "qorvex-two", "QORVEX"))

    # Children of one parent are siblings; the same folder under another parent is fine.
    (other,) = conn.execute(INSERT_CATEGORY, ("topic", "zhyndel", "Zhyndel")).fetchone()
    child = "insert into categories (axis, name, folder, parent_id) values ('topic', %s, %s, %s)"
    conn.execute(child, ("qorvex/vlint", "Vlint", first))
    conn.execute(child, ("zhyndel/vlint", "vlint", other))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(child, ("qorvex/vlint-two", "VLINT", first))
    # The same folder on the other axis is a different grid cell.
    conn.execute(INSERT_CATEGORY, ("format", "qorvex-fmt", "Qorvex"))


def test_prompts_unique_position_and_cascade(conn: psycopg.Connection) -> None:
    (cid,) = conn.execute(INSERT_CATEGORY, ("topic", "qorvex", "Qorvex")).fetchone()
    insert = "insert into category_prompts (category_id, position, prompt) values (%s, %s, %s)"
    conn.execute(insert, (cid, 0, "a qorvex"))
    conn.execute(insert, (cid, 1, "a zhyndel"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(insert, (cid, 1, "again"))
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute(insert, (cid + 10_000, 0, "orphan"))
    with pytest.raises(psycopg.errors.NotNullViolation):
        conn.execute(insert, (cid, 2, None))

    conn.execute("delete from categories where id = %s", (cid,))
    assert conn.execute(
        "select count(*) from category_prompts where category_id = %s", (cid,)
    ).fetchone() == (0,)


def test_parent_fk_blocks_deleting_a_parent(conn: psycopg.Connection) -> None:
    (parent,) = conn.execute(INSERT_CATEGORY, ("topic", "qorvex", "Qorvex")).fetchone()
    conn.execute(
        "insert into categories (axis, name, folder, parent_id) values ('topic', 'c', 'C', %s)",
        (parent,),
    )
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        conn.execute("delete from categories where id = %s", (parent,))


def test_image_vec_round_trip(conn: psycopg.Connection) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    assert conn.execute("select image_vec from files").fetchone() == (None,)
    vec = "[" + ",".join(["0.5"] * 1152) + "]"
    conn.execute("update files set image_vec = %s::vector", (vec,))
    assert conn.execute("select vector_dims(image_vec) from files").fetchone() == (1152,)
    with pytest.raises(psycopg.errors.DataException):  # wrong dimension is refused
        conn.execute("update files set image_vec = '[1,2,3]'::vector")


def test_downgrade_to_0002_and_back(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        c.execute(INSERT_FILE, (HASH,))
        c.execute("update files set format = 'photos', original_sanitized = 'x'")

    command.downgrade(alembic_cfg, "0002")
    for table in ("categories", "category_prompts"):
        assert _rows(schema, f"select to_regclass('\"{schema}\".{table}')::text") == [(None,)]
    assert "image_vec" not in _columns(schema, "files")
    # Only what 0003 added is gone: files rows and 0002's column survive.
    assert _rows(schema, "select source_hash, format, original_sanitized from files") == [
        (HASH, "photos", "x")
    ]
    assert _rows(schema, "select count(*) from sanitize_log") == [(0,)]
    assert _rows(schema, "select version_num from alembic_version") == [("0002",)]

    command.upgrade(alembic_cfg, "head")
    assert _columns(schema, "files")["image_vec"] is True
