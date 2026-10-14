"""`classifier categories`: manage both axes' categories in the local database (CLI-004.1).

Postgres only, no file system access (P-5). Prompts and `min_score` are hand-tuned values
(CLAUDE.md §1.7): they live in the local database and are never committed. Edits apply to the
next classify, not to rows already classified (CLI-004.D2).

Console output is category configuration only (names, folders, scores): never a file name, a
path or a count of files. Every error is a fixed text, raised outside any `except` block so
`__cause__` and `__context__` stay None; the user's input is never quoted (R-CLS-7, P-5).
"""

from typing import Annotated

import psycopg
import typer

from classifier.config import Config, ConfigError, load_config

categories_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Manage the format and topic categories."
)

_ERR_CONFIG = "the config could not be loaded; check the config file and DB_DSN"
_ERR_DB = "database error, see the db service logs"


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


ConfigOption = Annotated[
    str | None, typer.Option("--config", help="Config file; default $CLASSIFIER_CONFIG.")
]


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


@categories_app.command("list")
def list_categories(
    config_path: ConfigOption = None,
) -> None:
    """List every category: axis, name, folder, min_score, branch, parent, prompt count."""
    _config, conn = _open(config_path)
    problem = None
    rows: list[tuple] = []
    try:
        with conn:
            rows = conn.execute(
                "select c.axis, c.name, c.folder, c.min_score, c.branch, p.name, "
                "(select count(*) from category_prompts cp where cp.category_id = c.id) "
                "from categories c left join categories p on p.id = c.parent_id "
                "order by c.axis, c.name"
            ).fetchall()
    except psycopg.Error:
        problem = _ERR_DB
    finally:
        conn.close()
    if problem is not None:
        raise _fail(problem, 1)
    typer.echo("axis\tname\tfolder\tmin_score\tbranch\tparent\tprompts")
    for axis, name, folder, min_score, branch, parent, prompts in rows:
        score = "axis default" if min_score is None else f"{min_score:g}"
        typer.echo(f"{axis}\t{name}\t{folder}\t{score}\t{branch}\t{parent or '-'}\t{prompts}")
