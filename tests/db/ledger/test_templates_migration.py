"""DB-009.1 acceptance: migration 0008 adds `naming_templates` and `template_assignments`.

Isolated like test_runs_migration.py: a throwaway schema per test, dropped with `cascade`.
Every value is synthetic; refusals are asserted on the constraint name only.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint, Engine, create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from classifier.db.models import TEMPLATE_SCOPES, NamingTemplate, TemplateAssignment
from classifier.db.url import to_sqlalchemy_url
from tests.db.db_support import require_db_dsn

INI = Path(__file__).resolve().parents[3] / "classifier" / "db" / "alembic.ini"

# Typed out from NAME-001.D1 and NAME-001.D2 (docs/plans/m5.md), not imported from 0008.
GOLDEN = {
    "descriptive": "{subject}_{detail|max=40}_{seq:3}",
    "reference": "{reference|or={subject}}_{seq:3}",
    "dated": "{date}_{subject}_{seq:3}",
    "category-seq": "{category}_{seq:4}",
    "keep-original": "{original_sanitized}",
    "hash": "{short_hash}",
}
TEMPLATE_COLUMNS = {
    "id": ("integer", False), "name": ("text", False), "template": ("text", False),
    "builtin": ("boolean", False), "created_at": ("timestamp with time zone", False),
}  # fmt: skip
ASSIGNMENT_COLUMNS = {
    "id": ("integer", False), "scope": ("text", False), "category_id": ("integer", True),
    "template_id": ("integer", False), "created_at": ("timestamp with time zone", False),
}  # fmt: skip
CHECKS = {
    "naming_templates": {"naming_templates_name", "naming_templates_template"},
    "template_assignments": {"template_assignments_scope", "template_assignments_scope_category"},
}
INDEXES = {
    "naming_templates": {"naming_templates_pkey", "uq_naming_templates_name"},
    "template_assignments": {
        "template_assignments_pkey",
        "uq_template_assignments_category_id",
        "uq_template_assignments_global",
    },
}
ADD_TEMPLATE = "insert into naming_templates (name, template) values (%s, %s)"


@pytest.fixture
def schema() -> Iterator[str]:
    name = f"mig_{uuid.uuid4().hex[:12]}"
    with psycopg.connect(require_db_dsn(), autocommit=True) as conn:
        conn.execute(f'create schema "{name}"')
        try:
            yield name
        finally:
            conn.execute(f'drop schema "{name}" cascade')


def _url(schema: str) -> str:
    url = make_url(to_sqlalchemy_url(require_db_dsn())).update_query_dict(
        {"options": f"-c search_path={schema},public"}
    )
    return url.render_as_string(hide_password=False)


@pytest.fixture
def alembic_cfg(schema: str) -> Config:
    cfg = Config(str(INI))
    cfg.set_main_option("sqlalchemy.url", _url(schema).replace("%", "%%"))
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


@pytest.fixture
def engine(conn: psycopg.Connection, schema: str) -> Iterator[Engine]:
    eng = create_engine(_url(schema))
    try:
        yield eng
    finally:
        eng.dispose()


def _columns(c: psycopg.Connection, schema: str, table: str) -> dict[str, tuple[str, bool]]:
    rows = c.execute(
        "select column_name, data_type, is_nullable = 'YES' from information_schema.columns "
        "where table_schema = %s and table_name = %s",
        (schema, table),
    ).fetchall()
    return {name: (kind, nullable) for name, kind, nullable in rows}


def _seed(c: psycopg.Connection) -> dict[str, tuple[str, bool]]:
    rows = c.execute("select name, template, builtin from naming_templates").fetchall()
    return {name: (template, builtin) for name, template, builtin in rows}


def _template_id(c: psycopg.Connection, name: str) -> int:
    return c.execute("select id from naming_templates where name = %s", (name,)).fetchone()[0]


def _category_ids(c: psycopg.Connection) -> list[int]:
    return [i for (i,) in c.execute("select id from categories order by id limit 2").fetchall()]


def _assign(c: psycopg.Connection, scope: str, category_id: int | None, template_id: int) -> None:
    c.execute(
        "insert into template_assignments (scope, category_id, template_id) values (%s, %s, %s)",
        (scope, category_id, template_id),
    )


# --- shape --------------------------------------------------------------------------------


def test_0008_extends_0007_and_is_the_single_head(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert script.get_heads() == ["0008"]
    assert script.get_revision("0008").down_revision == "0007"


def test_upgrade_adds_both_tables(conn: psycopg.Connection, schema: str) -> None:
    assert _columns(conn, schema, "naming_templates") == TEMPLATE_COLUMNS
    assert _columns(conn, schema, "template_assignments") == ASSIGNMENT_COLUMNS
    for table, names in CHECKS.items():
        rows = conn.execute(
            "select conname from pg_constraint where conrelid = %s::regclass and contype = 'c'",
            (table,),
        ).fetchall()
        assert {n for (n,) in rows} == names
    for table, names in INDEXES.items():
        rows = conn.execute(
            "select indexname from pg_indexes where schemaname = %s and tablename = %s",
            (schema, table),
        ).fetchall()
        assert {n for (n,) in rows} == names
    assert conn.execute("select version_num from alembic_version").fetchall() == [("0008",)]


def _db_shape(conn: psycopg.Connection) -> dict[str, str]:
    """Postgres's own rendering of every constraint and index on the two tables."""
    rows = conn.execute(
        "select conname, pg_get_constraintdef(oid) from pg_constraint "
        "where conrelid in ('naming_templates'::regclass, 'template_assignments'::regclass)"
    ).fetchall()
    shape = dict(rows)
    rows = conn.execute(
        "select indexname, regexp_replace(indexdef, ' ON \\S+\\.', ' ON ') from pg_indexes "
        "where schemaname = current_schema() "
        "and tablename in ('naming_templates', 'template_assignments')"
    ).fetchall()
    shape.update(rows)
    return shape


def test_the_orm_mirrors_the_migration(conn: psycopg.Connection, schema: str) -> None:
    for model, table in ((NamingTemplate, "naming_templates"),
                         (TemplateAssignment, "template_assignments")):  # fmt: skip
        orm = {c.name for c in model.__table__.constraints if isinstance(c, CheckConstraint)}
        assert orm == CHECKS[table]
    # Same SQL: create the ORM's tables in a second schema and compare Postgres's rendering.
    mirror = f"{schema}_orm"
    conn.execute(f'create schema "{mirror}"')
    try:
        engine = create_engine(_url(mirror))
        try:
            with engine.begin() as c:
                c.exec_driver_sql("create table categories (id integer primary key)")
            NamingTemplate.__table__.create(engine)
            TemplateAssignment.__table__.create(engine)
        finally:
            engine.dispose()
        conn.execute(f'set search_path to "{mirror}", public')
        from_orm = _db_shape(conn)
        conn.execute(f'set search_path to "{schema}", public')
        assert from_orm == _db_shape(conn)
    finally:
        conn.execute(f'drop schema "{mirror}" cascade')
    assert TEMPLATE_SCOPES == ("global", "category")


# --- the seed -----------------------------------------------------------------------------


def test_the_six_builtins_are_seeded_exactly(conn: psycopg.Connection) -> None:
    assert _seed(conn) == {name: (template, True) for name, template in GOLDEN.items()}


def test_the_global_default_is_descriptive(conn: psycopg.Connection) -> None:
    """DB-009.D1: R-NAME-1's default is a row, so set-default is a plain update."""
    rows = conn.execute(
        "select a.scope, a.category_id, t.name from template_assignments a "
        "join naming_templates t on t.id = a.template_id"
    ).fetchall()
    assert rows == [("global", None, "descriptive")]


def test_a_user_template_defaults_to_not_builtin(conn: psycopg.Connection) -> None:
    conn.execute(ADD_TEMPLATE, ("qorvex", "{subject}_Zhyndel"))
    assert _seed(conn)["qorvex"] == ("{subject}_Zhyndel", False)


# --- naming_templates CHECKs --------------------------------------------------------------


@pytest.mark.parametrize("name", ["q", "q" * 32, "qorvex-zhyndel", "q0-9", "z-"])
def test_a_good_name_is_accepted(conn: psycopg.Connection, name: str) -> None:
    conn.execute(ADD_TEMPLATE, (name, "{short_hash}"))
    assert name in _seed(conn)


@pytest.mark.parametrize(
    "name",
    ["", "Qorvex", "qorveX", "0qorvex", "-qorvex", "qorvex_zhyndel", "q" * 33, "qorvex zhyndel",
     "qorvex.zhyndel", "qorvex/zhyndel", "qorvéx", "qorvex\n"],
)  # fmt: skip
def test_a_bad_name_is_refused(conn: psycopg.Connection, name: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        conn.execute(ADD_TEMPLATE, (name, "{short_hash}"))
    assert caught.value.diag.constraint_name == "naming_templates_name"
    assert len(_seed(conn)) == len(GOLDEN)


def test_a_duplicate_name_is_refused(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.UniqueViolation) as caught:
        conn.execute(ADD_TEMPLATE, ("hash", "{subject}"))
    assert caught.value.diag.constraint_name == "uq_naming_templates_name"


@pytest.mark.parametrize("template", ["x", "x" * 200, " {subject} ", "{subject}_Zhyndel ß"])
def test_a_good_template_is_accepted(conn: psycopg.Connection, template: str) -> None:
    conn.execute(ADD_TEMPLATE, ("qorvex", template))
    assert _seed(conn)["qorvex"] == (template, False)


@pytest.mark.parametrize(
    "template",
    ["", " ", "   ", "x" * 201, "{subject}\n{seq:3}", "{subject}\r", "\t{subject}",
     "{subject}\x7f", "{subject}\x1b", "{subject} ", "{subject} ", "{subject}\u0085"],
)  # fmt: skip
def test_a_bad_template_is_refused(conn: psycopg.Connection, template: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        conn.execute(ADD_TEMPLATE, ("qorvex", template))
    assert caught.value.diag.constraint_name == "naming_templates_template"
    assert "qorvex" not in _seed(conn)


# --- template_assignments -----------------------------------------------------------------


def test_one_assignment_per_category_is_accepted(conn: psycopg.Connection) -> None:
    first, second = _category_ids(conn)
    _assign(conn, "category", first, _template_id(conn, "hash"))
    _assign(conn, "category", second, _template_id(conn, "dated"))
    assert conn.execute("select count(*) from template_assignments").fetchone() == (3,)


@pytest.mark.parametrize(
    ("scope", "with_category", "check"),
    [
        ("global", True, "template_assignments_scope_category"),
        ("category", False, "template_assignments_scope_category"),
        ("Global", False, "template_assignments_scope"),
        ("qorvex", True, "template_assignments_scope"),
        ("", False, "template_assignments_scope"),
    ],
)
def test_a_bad_assignment_is_refused(
    conn: psycopg.Connection, scope: str, with_category: bool, check: str
) -> None:
    category = _category_ids(conn)[0] if with_category else None
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        _assign(conn, scope, category, _template_id(conn, "hash"))
    assert caught.value.diag.constraint_name == check
    assert conn.execute("select count(*) from template_assignments").fetchone() == (1,)


def test_a_second_global_is_refused(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.UniqueViolation) as caught:
        _assign(conn, "global", None, _template_id(conn, "hash"))
    assert caught.value.diag.constraint_name == "uq_template_assignments_global"


def test_a_second_assignment_for_one_category_is_refused(conn: psycopg.Connection) -> None:
    category = _category_ids(conn)[0]
    _assign(conn, "category", category, _template_id(conn, "hash"))
    with pytest.raises(psycopg.errors.UniqueViolation) as caught:
        _assign(conn, "category", category, _template_id(conn, "dated"))
    assert caught.value.diag.constraint_name == "uq_template_assignments_category_id"


def test_unknown_references_are_refused(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as caught:
        _assign(conn, "category", 999_999, _template_id(conn, "hash"))
    assert caught.value.diag.constraint_name == "fk_template_assignments_category_id_categories"
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as caught:
        _assign(conn, "category", _category_ids(conn)[0], 999_999)
    assert (
        caught.value.diag.constraint_name == "fk_template_assignments_template_id_naming_templates"
    )


def test_deleting_a_category_drops_its_assignment(conn: psycopg.Connection) -> None:
    conn.execute("insert into categories (axis, name, folder) values ('topic', 'qorvex', 'Qorvex')")
    category = conn.execute("select id from categories where name = 'qorvex'").fetchone()[0]
    _assign(conn, "category", category, _template_id(conn, "hash"))
    conn.execute("delete from categories where id = %s", (category,))
    rows = conn.execute("select scope from template_assignments").fetchall()
    assert rows == [("global",)]


def test_an_assigned_template_cannot_be_deleted(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation) as caught:
        conn.execute("delete from naming_templates where name = 'descriptive'")
    assert (
        caught.value.diag.constraint_name == "fk_template_assignments_template_id_naming_templates"
    )
    # An unassigned one can (DB-009.D2: CLI-010, not the schema, protects built-ins).
    conn.execute("delete from naming_templates where name = 'hash'")
    assert "hash" not in _seed(conn)


def test_set_default_is_a_plain_update(conn: psycopg.Connection) -> None:
    conn.execute(
        "update template_assignments set template_id = %s where scope = 'global'",
        (_template_id(conn, "hash"),),
    )
    rows = conn.execute(
        "select t.name from template_assignments a join naming_templates t on t.id = a.template_id"
    ).fetchall()
    assert rows == [("hash",)]


# --- ORM and repr -------------------------------------------------------------------------


def test_templates_round_trip_through_the_orm(engine: Engine) -> None:
    with Session(engine) as session:
        template = NamingTemplate(name="qorvex", template="{subject}_Zhyndel_{seq:3}")
        session.add(template)
        session.flush()
        category = session.connection().exec_driver_sql("select min(id) from categories").scalar()
        assignment = TemplateAssignment(
            scope="category", category_id=category, template_id=template.id
        )
        session.add(assignment)
        session.commit()
        template_id, assignment_id = template.id, assignment.id

    with Session(engine) as session:
        back = session.get(NamingTemplate, template_id)
        assert back is not None
        assert (back.name, back.template, back.builtin) == (
            "qorvex", "{subject}_Zhyndel_{seq:3}", False,
        )  # fmt: skip
        link = session.get(TemplateAssignment, assignment_id)
        assert link is not None
        assert (link.scope, link.category_id, link.template_id) == (
            "category", category, template_id,
        )  # fmt: skip


def test_the_reprs_hold_no_name_or_template(engine: Engine) -> None:
    """Privacy item 19: planted values are held by the row, and absent from repr and str."""
    name_plant, template_plant = "qorvex-zhyndel", "{subject}_Zhyndelmark_Qorvexton"
    with Session(engine) as session:
        template = NamingTemplate(name=name_plant, template=template_plant)
        session.add(template)
        session.commit()
        # Held first, so the absence below is meaningful.
        assert template.name == name_plant and template.template == template_plant
        assignment = TemplateAssignment(scope="global", category_id=None, template_id=template.id)
        for text in (repr(template), str(template)):
            assert text == f"NamingTemplate(id={template.id!r}, builtin=False)"
            for plant in (name_plant, template_plant, "Zhyndelmark", "Qorvexton", "qorvex"):
                assert plant not in text
        for text in (repr(assignment), str(assignment)):
            assert text == (
                f"TemplateAssignment(id=None, scope='global', category_id=None, "
                f"template_id={template.id!r})"
            )
            assert "qorvex" not in text and "Zhyndel" not in text


# --- downgrade ----------------------------------------------------------------------------


def test_downgrade_drops_both_tables_and_upgrade_restores_the_seed(
    alembic_cfg: Config, conn: psycopg.Connection, schema: str
) -> None:
    conn.execute(ADD_TEMPLATE, ("qorvex", "{subject}_Zhyndel"))
    command.downgrade(alembic_cfg, "0007")
    assert _columns(conn, schema, "naming_templates") == {}
    assert _columns(conn, schema, "template_assignments") == {}
    assert conn.execute("select version_num from alembic_version").fetchall() == [("0007",)]
    # The earlier tables are untouched.
    assert conn.execute("select count(*) > 0 from categories").fetchone() == (True,)
    assert _columns(conn, schema, "runs") != {}

    command.upgrade(alembic_cfg, "head")
    assert _seed(conn) == {name: (template, True) for name, template in GOLDEN.items()}
    assert conn.execute("select scope from template_assignments").fetchall() == [("global",)]
