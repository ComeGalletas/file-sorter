"""CLI-010.1 acceptance: `classifier templates list|add|set-default|assign|preview` (DESIGN §7,
R-NAME-1; CLI-010.D1; DB-009.D2).

Each module gets a throwaway schema at Alembic head and points `DB_DSN` at it, so the command's
own connection sees committed rows and nothing leaks into other db tests. Every template name,
category name and token value is a synthetic coinage.
"""

import logging
import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import click
import psycopg
import pytest
import typer
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from classifier.cli import app
from classifier.db.url import to_sqlalchemy_url
from tests.db.db_support import require_db_dsn

ROOT = Path(__file__).resolve().parents[3]
INI = ROOT / "classifier" / "db" / "alembic.ini"
CONFIG = str(ROOT / "config.yaml")
runner = CliRunner()

BUILTIN_ROWS = [
    ("descriptive", True, "{subject}_{detail|max=40}_{seq:3}"),
    ("reference", True, "{reference|or={subject}}_{seq:3}"),
    ("dated", True, "{date}_{subject}_{seq:3}"),
    ("category-seq", True, "{category}_{seq:4}"),
    ("keep-original", True, "{original_sanitized}"),
    ("hash", True, "{short_hash}"),
]


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    name = f"cli_{uuid.uuid4().hex[:12]}"
    base = require_db_dsn()
    url = make_url(to_sqlalchemy_url(base)).update_query_dict(
        {"options": f"-c search_path={name},public"}
    )
    options = quote(f"-c search_path={name},public", safe="")
    dsn = f"{base}{'&' if '?' in base else '?'}options={options}"
    with psycopg.connect(base, autocommit=True) as admin:
        admin.execute(f'create schema "{name}"')
        try:
            cfg = Config(str(INI))
            cfg.set_main_option(
                "sqlalchemy.url", url.render_as_string(hide_password=False).replace("%", "%%")
            )
            command.upgrade(cfg, "head")
            yield dsn
        finally:
            admin.execute(f'drop schema "{name}" cascade')


def _snapshot(dsn: str) -> tuple[list[tuple], list[tuple], list[int]]:
    with psycopg.connect(dsn) as conn:
        templates = conn.execute(
            "select id, name, template, builtin from naming_templates order by id"
        ).fetchall()
        assignments = conn.execute(
            "select scope, category_id, template_id from template_assignments order by id"
        ).fetchall()
        categories = [r[0] for r in conn.execute("select id from categories order by id")]
    return templates, assignments, categories


@pytest.fixture
def cli(schema_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the command at the schema; restore the seeded rows afterwards, even on failure."""
    monkeypatch.setenv("DB_DSN", schema_dsn)
    seed = _snapshot(schema_dsn)
    seed_templates, seed_assignments, seed_categories = seed
    yield
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("delete from template_assignments")
        conn.execute(
            "delete from naming_templates where id <> all(%s)",
            ([row[0] for row in seed_templates] or [0],),
        )
        for row_id, name, template, builtin in seed_templates:
            conn.execute(
                "update naming_templates set name = %s, template = %s, builtin = %s where id = %s",
                (name, template, builtin, row_id),
            )
        conn.execute("delete from categories where id <> all(%s)", (seed_categories or [0],))
        for scope, category_id, template_id in seed_assignments:
            conn.execute(
                "insert into template_assignments (scope, category_id, template_id) "
                "values (%s, %s, %s)",
                (scope, category_id, template_id),
            )
    after = _snapshot(schema_dsn)
    assert after[0] == seed_templates and after[2] == seed_categories
    assert sorted(after[1], key=str) == sorted(seed_assignments, key=str)


def run(*args: str):
    return runner.invoke(app, ["templates", *args, "--config", CONFIG])


def _rows(dsn: str, sql: str, *params: object) -> list[tuple]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, params).fetchall()


def _category(dsn: str, axis: str, name: str) -> int:
    with psycopg.connect(dsn) as conn:
        row = conn.execute(
            "insert into categories (axis, name, folder, branch, description) "
            "values (%s, %s, %s, 'any', 'A synthetic stand-in') returning id",
            (axis, name, name),
        ).fetchone()
    assert row is not None
    return row[0]


def _assigned(dsn: str) -> list[tuple]:
    return _rows(
        dsn,
        "select a.scope, c.axis, c.name, t.name from template_assignments a "
        "join naming_templates t on t.id = a.template_id "
        "left join categories c on c.id = a.category_id order by a.scope desc, c.name",
    )


def _plant_absent(result, plant: str, caplog: pytest.LogCaptureFixture) -> None:
    """The plant never reaches stdout, stderr, the exit, the exception chain or the logs."""
    assert plant not in result.output
    assert plant not in (result.stderr or "")
    # click turns typer.Exit into SystemExit, so the chain is SystemExit <- Exit. Neither
    # may carry the plant, and no driver or library error may sit anywhere in the chain.
    seen = 0
    exc = result.exception
    while exc is not None:
        seen += 1
        assert isinstance(exc, (SystemExit, click.exceptions.Exit, typer.Exit)), type(exc).__name__
        assert plant not in str(exc) and plant not in repr(exc)
        assert exc.__cause__ is None
        exc = exc.__context__
    assert seen >= 1  # the command did exit with an error
    for record in caplog.records:
        assert plant not in record.getMessage()


# --- list ---------------------------------------------------------------------------------


def test_list_shows_the_builtins_and_the_global_default(cli: None) -> None:
    result = run("list")
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0] == "name\tbuiltin\ttemplate\tassigned"
    expected = [
        f"{name}\tyes\t{template}\t{'global' if name == 'descriptive' else '-'}"
        for name, _builtin, template in BUILTIN_ROWS
    ]
    assert lines[1:] == expected


# --- add ----------------------------------------------------------------------------------


def test_add_stores_a_user_template(cli: None, schema_dsn: str) -> None:
    result = run("add", "zhyndel-flat", "{subject}_{seq:3}")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "added template zhyndel-flat"
    assert _rows(
        schema_dsn, "select template, builtin from naming_templates where name = 'zhyndel-flat'"
    ) == [("{subject}_{seq:3}", False)]
    assert "zhyndel-flat\tno\t{subject}_{seq:3}\t-" in run("list").output


@pytest.mark.parametrize(
    "name", ["Qorvex", "1qorvex", "qorvex_flat", "q" * 33, "qor vex", "qor\udcffvex"]
)
def test_add_refuses_a_bad_name(cli: None, schema_dsn: str, name: str) -> None:
    result = run("add", name, "{subject}")
    assert result.exit_code == 2
    assert "a template name is 1 to 32 characters" in result.output
    assert _rows(schema_dsn, "select count(*) from naming_templates") == [(6,)]


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("{qorvex}", "unknown template token"),
        ("{subject|zhyndel}", "unknown template filter"),
        ("qorvex", "template has no token"),
        ("{subject" + "x" * 200 + "}", "template is longer than 200 characters"),
        ("{subject}\tqorvex", "the template must be one line"),
        ("{subject}" + chr(0x2028) + "qorvex", "the template must be one line"),
        ("{subject}\udcffqorvex", "the template must be one line"),
    ],
)
def test_add_refuses_a_bad_template(
    cli: None, schema_dsn: str, template: str, message: str
) -> None:
    result = run("add", "zhyndel-flat", template)
    assert result.exit_code == 2
    assert f"error: {message}" in result.output
    assert "qorvex" not in result.output and "zhyndel}" not in result.output
    assert _rows(schema_dsn, "select count(*) from naming_templates") == [(6,)]


def test_add_refuses_a_builtin_name(cli: None, schema_dsn: str) -> None:
    # DB-009.D2: a built-in can't be replaced.
    result = run("add", "descriptive", "{short_hash}")
    assert result.exit_code == 2
    assert result.output.strip() == "error: a template with that name already exists"
    assert _rows(
        schema_dsn, "select template, builtin from naming_templates where name = 'descriptive'"
    ) == [("{subject}_{detail|max=40}_{seq:3}", True)]


def test_duplicate_add_never_echoes_the_key(
    cli: None, schema_dsn: str, caplog: pytest.LogCaptureFixture
) -> None:
    # #268's audit: Postgres's DETAIL echoes `Key (name)=(...)`. Plant a coined name and a
    # coined token text, prove both are held, then show the duplicate's failure omits them.
    caplog.set_level(logging.DEBUG)
    plant, text_plant = "qorvexplant", "zhyndeltext"
    first = run("add", plant, "{subject}_" + text_plant)
    assert first.exit_code == 0, first.output
    assert _rows(schema_dsn, "select template from naming_templates where name = %s", plant) == [
        ("{subject}_" + text_plant,)
    ]
    assert plant in run("list").output  # held
    caplog.clear()
    second = run("add", plant, "{short_hash}_" + text_plant)
    assert second.exit_code == 2
    assert second.output.strip() == "error: a template with that name already exists"
    _plant_absent(second, plant, caplog)
    _plant_absent(second, text_plant, caplog)
    assert "Key (" not in second.output


def test_db_unreachable_is_fixed_text(cli: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_DSN", "postgresql://nobody:pw-qorvex@127.0.0.1:1/none")
    result = run("list")
    assert result.exit_code == 1
    assert result.output.strip() == "error: database error, see the db service logs"
    assert "pw-qorvex" not in result.output


# --- set-default --------------------------------------------------------------------------


def test_set_default_moves_the_global_row(cli: None, schema_dsn: str) -> None:
    assert run("set-default", "hash").exit_code == 0
    assert _assigned(schema_dsn) == [("global", None, None, "hash")]
    again = run("set-default", "hash")  # idempotent
    assert again.exit_code == 0 and again.output.strip() == "default template set to hash"
    assert _assigned(schema_dsn) == [("global", None, None, "hash")]
    assert "hash\tyes\t{short_hash}\tglobal" in run("list").output


def test_set_default_to_a_user_template(cli: None, schema_dsn: str) -> None:
    assert run("add", "zhyndel-flat", "{subject}").exit_code == 0
    assert run("set-default", "zhyndel-flat").exit_code == 0
    assert _assigned(schema_dsn) == [("global", None, None, "zhyndel-flat")]


def test_set_default_refuses_a_missing_template(
    cli: None, schema_dsn: str, caplog: pytest.LogCaptureFixture
) -> None:
    result = run("set-default", "qorvexmissing")
    assert result.exit_code == 2
    assert result.output.strip() == "error: no such template"
    _plant_absent(result, "qorvexmissing", caplog)
    assert _assigned(schema_dsn) == [("global", None, None, "descriptive")]


# --- assign -------------------------------------------------------------------------------


def test_assign_per_category_on_both_axes(cli: None, schema_dsn: str) -> None:
    _category(schema_dsn, "format", "Glorpic")
    _category(schema_dsn, "topic", "Vexmoor")
    one = run("assign", "dated", "--axis", "format", "--category", "Glorpic")
    assert one.exit_code == 0, one.output
    assert one.output.strip() == "assigned template dated to format category Glorpic"
    assert run("assign", "hash", "--axis", "topic", "--category", "Vexmoor").exit_code == 0
    assert _assigned(schema_dsn) == [
        ("global", None, None, "descriptive"),
        ("category", "format", "Glorpic", "dated"),
        ("category", "topic", "Vexmoor", "hash"),
    ]
    listed = run("list").output
    assert "dated\tyes\t{date}_{subject}_{seq:3}\tformat:Glorpic" in listed
    assert "hash\tyes\t{short_hash}\ttopic:Vexmoor" in listed


def test_reassign_moves_the_category(cli: None, schema_dsn: str) -> None:
    _category(schema_dsn, "topic", "Vexmoor")
    assert run("assign", "dated", "--axis", "topic", "--category", "Vexmoor").exit_code == 0
    assert run("assign", "hash", "--axis", "topic", "--category", "Vexmoor").exit_code == 0
    assert _assigned(schema_dsn) == [
        ("global", None, None, "descriptive"),
        ("category", "topic", "Vexmoor", "hash"),
    ]


def test_clear_falls_back_to_global(cli: None, schema_dsn: str) -> None:
    _category(schema_dsn, "topic", "Vexmoor")
    assert run("assign", "dated", "--axis", "topic", "--category", "Vexmoor").exit_code == 0
    cleared = run("assign", "--clear", "--axis", "topic", "--category", "Vexmoor")
    assert cleared.exit_code == 0, cleared.output
    assert cleared.output.strip() == "cleared the template of topic category Vexmoor"
    assert _assigned(schema_dsn) == [("global", None, None, "descriptive")]
    again = run("assign", "--clear", "--axis", "topic", "--category", "Vexmoor")
    assert again.exit_code == 0  # idempotent


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("dated", "--clear", "--axis", "topic", "--category", "Vexmoor"), "pass a template name"),
        (("--axis", "topic", "--category", "Vexmoor"), "pass a template name"),
        (("dated", "--axis", "qorvex", "--category", "Vexmoor"), "--axis must be format or topic"),
        (("dated", "--axis", "topic", "--category", "  "), "the category name is empty"),
        (("Dated", "--axis", "topic", "--category", "Vexmoor"), "a template name is 1 to 32"),
        (("qorvexmissing", "--axis", "topic", "--category", "Vexmoor"), "no such template"),
    ],
)
def test_assign_refusals(cli: None, schema_dsn: str, args: tuple[str, ...], message: str) -> None:
    _category(schema_dsn, "topic", "Vexmoor")
    result = run("assign", *args)
    assert result.exit_code == 2
    assert result.output.startswith(f"error: {message}")
    assert "qorvex" not in result.output
    assert _assigned(schema_dsn) == [("global", None, None, "descriptive")]


def test_assign_to_a_missing_category_never_echoes_it(
    cli: None, schema_dsn: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    plant = "Qorvexcatplant"
    _category(schema_dsn, "format", plant)  # held on the other axis
    assert _rows(schema_dsn, "select count(*) from categories where name = %s", plant) == [(1,)]
    result = run("assign", "dated", "--axis", "topic", "--category", plant)
    assert result.exit_code == 2
    assert result.output.strip() == "error: no such category on this axis"
    _plant_absent(result, plant, caplog)


def test_assigned_template_is_listed_once_per_scope(cli: None, schema_dsn: str) -> None:
    _category(schema_dsn, "format", "Glorpic")
    _category(schema_dsn, "topic", "Vexmoor")
    for axis, name in (("format", "Glorpic"), ("topic", "Vexmoor")):
        assert run("assign", "descriptive", "--axis", axis, "--category", name).exit_code == 0
    listed = run("list").output
    assert "descriptive\tyes\t{subject}_{detail|max=40}_{seq:3}\tglobal,format:Glorpic," in listed
    assert listed.count("topic:Vexmoor") == 1


# --- preview (CLI-010.D1) -----------------------------------------------------------------

NAME_LINE = re.compile(r"[a-z0-9_]+\.(png|gif|webp)")


def _names(result) -> list[str]:
    lines = result.output.splitlines()
    assert lines[0].startswith("preview of template ")
    return lines[1:]


def test_preview_is_pinned_by_the_seed(cli: None) -> None:
    first = run("preview", "descriptive", "--sample", "20", "--seed", "7")
    again = run("preview", "descriptive", "--sample", "20", "--seed", "7")
    other = run("preview", "descriptive", "--sample", "20", "--seed", "8")
    assert first.exit_code == 0, first.output
    assert first.output == again.output
    assert _names(first) != _names(other)
    assert first.output.splitlines()[0] == (
        "preview of template descriptive: 20 synthetic rows, seed 7"
    )


def test_preview_default_seed_and_sample(cli: None) -> None:
    result = run("preview", "hash")
    assert result.exit_code == 0, result.output
    assert len(_names(result)) == 10
    assert result.output == run("preview", "hash", "--seed", "0", "--sample", "10").output


@pytest.mark.parametrize("name", ["descriptive", "reference", "dated", "category-seq",
                                  "keep-original", "hash"])  # fmt: skip
def test_preview_every_builtin(cli: None, name: str) -> None:
    result = run("preview", name, "--sample", "100", "--seed", "3")
    assert result.exit_code == 0, result.output
    names = _names(result)
    assert len(names) == 100
    for proposed in names:
        assert NAME_LINE.fullmatch(proposed), "a name is not normalized"
        assert len(proposed.rsplit(".", 1)[0]) <= 120
    # R-NAME-6 / NAME-001.D3: unique, compared casefolded.
    assert len({n.casefold() for n in names}) == len(names)


def test_preview_shows_the_adult_prefix_and_collisions(cli: None) -> None:
    names = _names(run("preview", "category-seq", "--sample", "40", "--seed", "1"))
    adult = [n for n in names if n.startswith("nsfw_")]
    assert adult and len(adult) < len(names)  # R-NAME-8 on adult rows only
    stems = [n.rsplit(".", 1)[0] for n in names]
    seqs = {s.rsplit("_", 1)[1] for s in stems}
    assert "0002" in seqs  # a collision incremented {seq}


def test_preview_uses_only_coined_text(cli: None) -> None:
    from classifier.cli.templates import (
        _DETAILS,
        _FORMATS,
        _ORIGINALS,
        _SUBJECTS,
        _TAGS,
        _TOPICS,
    )

    vocabulary = set()
    for text in (*_SUBJECTS, *_DETAILS, *_TAGS, *_FORMATS, *_ORIGINALS, *filter(None, _TOPICS)):
        vocabulary.update(text.lower().replace(".", "").split())
    names = _names(run("preview", "keep-original", "--sample", "30", "--seed", "5"))
    for proposed in names:
        stem = proposed.rsplit(".", 1)[0].removeprefix("nsfw_")
        words = [w for w in stem.split("_") if not w.isdigit()]
        assert set(words) <= vocabulary


def test_preview_of_a_user_template(cli: None) -> None:
    assert run("add", "zhyndel-flat", "{subject|max=4}").exit_code == 0
    names = _names(run("preview", "zhyndel-flat", "--sample", "12"))
    assert len(names) == 12
    # No {seq}: a collision appends _NNN (R-NAME-6, NAME-001.D6).
    assert any(n.rsplit(".", 1)[0].endswith("_001") for n in names)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (("descriptive", "--sample", "0"), "--sample must be from 1 to 100"),
        (("descriptive", "--sample", "101"), "--sample must be from 1 to 100"),
        (("descriptive", "--seed", "-1"), "--seed must be from 0"),
        (("descriptive", "--seed", str(2**32)), "--seed must be from 0"),
        (("Qorvex",), "a template name is 1 to 32"),
        (("qorvexmissing",), "no such template"),
    ],
)
def test_preview_refusals(cli: None, args: tuple[str, ...], message: str) -> None:
    result = run("preview", *args)
    assert result.exit_code == 2
    assert result.output.startswith(f"error: {message}")
    assert "qorvex" not in result.output.lower().replace("--", "")


def test_preview_of_a_template_edited_outside_the_cli(cli: None, schema_dsn: str) -> None:
    # A stored template the parser now refuses: fixed text, never the template.
    with psycopg.connect(schema_dsn) as conn:
        conn.execute(
            "insert into naming_templates (name, template) values ('zhyndel-raw', '{qorvex}')"
        )
    result = run("preview", "zhyndel-raw")
    assert result.exit_code == 2
    assert result.output.strip() == "error: unknown template token"


def test_preview_writes_and_logs_nothing(
    cli: None, schema_dsn: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    before = _snapshot(schema_dsn)
    assert run("preview", "descriptive", "--sample", "5").exit_code == 0
    assert _snapshot(schema_dsn) == before
    assert caplog.records == []
