"""`classifier templates`: manage naming templates in the local database (CLI-010.1; DESIGN §7,
R-NAME-1). `list` extends §7's set.

Postgres only, no file system access. Console output is template configuration only (names,
template text, assignments): never a file name, a path or a proposed name of a real image.
Every error is fixed text, raised outside any `except` block so `__cause__` and `__context__`
stay None. A driver message is never printed: Postgres's DETAIL echoes the key
(`Key (name)=(...)`), so every `psycopg.Error` becomes fixed text (#268's audit).
Built-ins can't be changed (DB-009.D2); assigning one is allowed.
"""

import re
import unicodedata
from typing import Annotated

import psycopg
import typer

from classifier.config import Config, ConfigError, load_config
from classifier.models.classify_rules import AXES
from classifier.naming.templates import TemplateError, parse

templates_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Manage the naming templates."
)

_ERR_CONFIG = "the config could not be loaded; check the config file and DB_DSN"
_ERR_DB = "database error, see the db service logs"
_ERR_NAME = "a template name is 1 to 32 characters: a-z first, then a-z, 0-9 or -"
_ERR_TEXT = "the template must be one line of valid text with no control characters"
_ERR_EXISTS = "a template with that name already exists"
_ERR_MISSING = "no such template"
_ERR_AXIS = "--axis must be format or topic"
_ERR_CATEGORY = "no such category on this axis"
_ERR_CATEGORY_TEXT = "the category name is empty, has a control character or is not valid text"
_ERR_ASSIGN = "pass a template name, or --clear, but not both"

_NAME = re.compile(r"[a-z][a-z0-9-]{0,31}")  # DB-009.1's naming_templates_name CHECK
_LINE_BREAKS = frozenset("\u0085  ")  # beyond Cc, as DB-009.1's template CHECK

ConfigOption = Annotated[
    str | None, typer.Option("--config", help="Config file; default $CLASSIFIER_CONFIG.")
]


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


def _encodes(value: str) -> bool:
    ok = True
    try:
        value.encode("utf-8")  # strict: a lone surrogate raises; its character is never quoted
    except UnicodeEncodeError:
        ok = False
    return ok


def _open(config_path: str | None) -> tuple[Config, psycopg.Connection]:
    """Load the config and connect, with fixed-text failures (exit 2 / exit 1)."""
    problem = None
    code = 2
    conn = None
    config = None
    try:
        config = load_config(config_path)
    except ConfigError:  # its text can carry a path
        problem = _ERR_CONFIG
    if problem is None:
        assert config is not None and config.db.dsn is not None
        try:
            conn = psycopg.connect(config.db.dsn)
        except psycopg.Error:  # a driver message can carry the DSN
            problem, code = _ERR_DB, 1
    if problem is not None:
        raise _fail(problem, code)
    assert config is not None and conn is not None
    return config, conn


def _run(config_path: str | None, work) -> None:
    """Open a transaction, run `work(conn)` -> problem text or None, and report it."""
    _config, conn = _open(config_path)
    problem = None
    code = 2
    try:
        with conn:  # commits on success, rolls back on error or when `work` returns a problem
            problem = work(conn)
            if problem is not None:
                conn.rollback()
    except psycopg.errors.UniqueViolation:  # its DETAIL quotes the key: never printed
        problem = _ERR_EXISTS
    except psycopg.Error:
        problem, code = _ERR_DB, 1
    finally:
        conn.close()
    if problem is not None:
        raise _fail(problem, code)


def _check_name(name: str) -> str | None:
    return None if _encodes(name) and _NAME.fullmatch(name) else _ERR_NAME


def _check_template(template: str) -> str | None:
    """The fixed-text problem with a template, or None (NAME-001's parser, then the CHECK)."""
    if not _encodes(template) or any(
        unicodedata.category(ch) == "Cc" or ch in _LINE_BREAKS for ch in template
    ):
        return _ERR_TEXT
    problem = None
    try:
        parse(template)
    except TemplateError as error:  # fixed text; it never quotes the template
        problem = str(error)
    return problem


def _template_id(conn: psycopg.Connection, name: str) -> int | None:
    row = conn.execute("select id from naming_templates where name = %s", (name,)).fetchone()
    return None if row is None else row[0]


@templates_app.command("list")
def list_templates(config_path: ConfigOption = None) -> None:
    """List every template: name, built-in or not, the template, and where it is assigned."""
    _config, conn = _open(config_path)
    problem = None
    rows: list[tuple] = []
    try:
        with conn:
            rows = conn.execute(
                "select t.name, t.builtin, t.template, "
                "string_agg(case when a.scope = 'global' then 'global' "
                "else c.axis || ':' || c.name end, ',' "
                "order by a.scope desc, c.axis, c.name) "
                "from naming_templates t "
                "left join template_assignments a on a.template_id = t.id "
                "left join categories c on c.id = a.category_id "
                "group by t.id order by t.builtin desc, t.id"
            ).fetchall()
    except psycopg.Error:
        problem = _ERR_DB
    finally:
        conn.close()
    if problem is not None:
        raise _fail(problem, 1)
    typer.echo("name\tbuiltin\ttemplate\tassigned")
    for name, builtin, template, assigned in rows:
        typer.echo(f"{name}\t{'yes' if builtin else 'no'}\t{template}\t{assigned or '-'}")


@templates_app.command("add")
def add_template(
    name: Annotated[str, typer.Argument(help="Template name: a-z first, then a-z, 0-9 or -.")],
    template: Annotated[str, typer.Argument(help="One line, at most 200 characters.")],
    config_path: ConfigOption = None,
) -> None:
    """Add a user template, validated by NAME-001's parser. Built-ins can't be replaced."""
    problem = _check_name(name) or _check_template(template)
    if problem is not None:
        raise _fail(problem)

    def work(conn: psycopg.Connection) -> str | None:
        conn.execute(
            "insert into naming_templates (name, template, builtin) values (%s, %s, false)",
            (name, template),
        )
        return None

    _run(config_path, work)
    typer.echo(f"added template {name}")


@templates_app.command("set-default")
def set_default(
    name: Annotated[str, typer.Argument(help="The template to use globally.")],
    config_path: ConfigOption = None,
) -> None:
    """Use a template for every category without its own assignment (R-NAME-1)."""
    problem = _check_name(name)
    if problem is not None:
        raise _fail(problem)

    def work(conn: psycopg.Connection) -> str | None:
        template_id = _template_id(conn, name)
        if template_id is None:
            return _ERR_MISSING
        conn.execute(
            "insert into template_assignments (scope, template_id) values ('global', %s) "
            "on conflict (scope) where scope = 'global' "
            "do update set template_id = excluded.template_id",
            (template_id,),
        )
        return None

    _run(config_path, work)
    typer.echo(f"default template set to {name}")


@templates_app.command("assign")
def assign_template(
    name: Annotated[str | None, typer.Argument(help="The template; omit it with --clear.")] = None,
    axis: Annotated[str, typer.Option("--axis", help="format or topic.")] = "",
    category: Annotated[str, typer.Option("--category", help="The category's name.")] = "",
    clear: Annotated[
        bool, typer.Option("--clear", help="Remove the category's assignment (use the global).")
    ] = False,
    config_path: ConfigOption = None,
) -> None:
    """Use a template for one category, or `--clear` it back to the global template."""
    problem = None
    if (name is None) == (not clear):
        problem = _ERR_ASSIGN
    if problem is None and name is not None:
        problem = _check_name(name)
    if problem is None and axis not in AXES:
        problem = _ERR_AXIS
    if problem is None and (
        not _encodes(category)
        or not category.strip()
        or any(unicodedata.category(ch) == "Cc" for ch in category)
    ):
        problem = _ERR_CATEGORY_TEXT
    if problem is not None:
        raise _fail(problem)
    category_name = category.strip()

    def work(conn: psycopg.Connection) -> str | None:
        row = conn.execute(
            "select id from categories where axis = %s and name = %s", (axis, category_name)
        ).fetchone()
        if row is None:
            return _ERR_CATEGORY
        if clear:
            conn.execute("delete from template_assignments where category_id = %s", (row[0],))
            return None
        assert name is not None
        template_id = _template_id(conn, name)
        if template_id is None:
            return _ERR_MISSING
        conn.execute(
            "insert into template_assignments (scope, category_id, template_id) "
            "values ('category', %s, %s) "
            "on conflict (category_id) do update set template_id = excluded.template_id",
            (row[0], template_id),
        )
        return None

    _run(config_path, work)
    if clear:
        typer.echo(f"cleared the template of {axis} category {category_name}")
    else:
        typer.echo(f"assigned template {name} to {axis} category {category_name}")
