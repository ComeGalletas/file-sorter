"""`classifier categories`: manage both axes' categories in the local database (CLI-004.1).

Postgres only, no file system access (P-5). Prompts and `min_score` are hand-tuned values
(CLAUDE.md §1.7): they live in the local database and are never committed. Edits apply to the
next classify, not to rows already classified (CLI-004.D2).

`--prompt` and `--min-score` are unused on the VLM path (CLS-004.D7). They stay accepted and
stored because DOC-009.D3 keeps the columns, and `add` no longer needs a prompt (CLI-006.1).

Console output is category configuration only (names, folders, scores): never a file name, a
path or a count of files. Every error is a fixed text, raised outside any `except` block so
`__cause__` and `__context__` stay None; the user's input is never quoted (R-CLS-7, P-5).
"""

import math
from typing import Annotated

import psycopg
import typer

from classifier.config import Config, ConfigError, load_config
from classifier.fileops.folders import FiledPair, FolderSyncError, sync_folders
from classifier.fileops.layout import LayoutError, validate_folder_segment
from classifier.models.classify_rules import (
    AXES,
    RULE_BRANCHES,
    UNSORTED,
    CategoryRule,
    ClassifyRulesError,
    validate_rules,
)

categories_app = typer.Typer(
    no_args_is_help=True, add_completion=False, help="Manage the format and topic categories."
)

_ERR_CONFIG = "the config could not be loaded; check the config file and DB_DSN"
_ERR_DB = "database error, see the db service logs"
_ERR_AXIS = "--axis must be format or topic"
_ERR_BRANCH = "--branch must be any, safe or nsfw"
_ERR_SCORE = "--min-score must be a number from 0 to 1"
_ERR_TEXT = "a name or prompt is empty, has a control character or is not valid text"
_ERR_PROMPTS = "at least one --prompt is required"
_ERR_RESERVED = "the unsorted category is protected"
_ERR_FOLDER = "invalid folder name"
_ERR_SIBLING = "a sibling category already uses that folder (compared ignoring case)"
_ERR_PARENT_MISSING = "the parent category does not exist on that axis"
_ERR_SCORE_BOTH = "--min-score and --reset-min-score cannot be used together"
_ERR_NOTHING = "nothing to change: pass --folder, --prompt, --min-score or --branch"
_ERR_CHILDREN = "the category has children; remove or move them first"
_ERR_EXISTS = "that category already exists on this axis"
_ERR_MISSING = "no such category on this axis"


def _fail(message: str, code: int = 2) -> typer.Exit:
    typer.echo(f"error: {message}", err=True)
    return typer.Exit(code)


_UNUSED_HELP = "Unused on the VLM path (CLS-004.D7), kept for the columns (DOC-009.D3)."

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
    """List every category: axis, name, folder, branch, parent and the unused min_score, prompts."""
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
    typer.echo("axis\tname\tfolder\tmin_score(unused)\tbranch\tparent\tprompts(unused)")
    for axis, name, folder, min_score, branch, parent, prompts in rows:
        score = "axis default" if min_score is None else f"{min_score:g}"
        typer.echo(f"{axis}\t{name}\t{folder}\t{score}\t{branch}\t{parent or '-'}\t{prompts}")


def _clean(value: str) -> str | None:
    """`value` stripped, or None if it is empty, has a control character or a lone surrogate."""
    problem = False
    try:
        value.encode("utf-8")  # strict: a lone surrogate raises, its character is never quoted
    except UnicodeEncodeError:
        problem = True
    text = value.strip()
    if problem or not text or any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in text):
        return None
    return text


def _check_common(
    axis: str, branch: str | None, min_score: float | None, prompts: list[str] | None
) -> tuple[str | None, list[str] | None]:
    """Fixed-text problem (or None) and the cleaned prompts (None when not given)."""
    if axis not in AXES:
        return _ERR_AXIS, None
    if branch is not None and branch not in RULE_BRANCHES:
        return _ERR_BRANCH, None
    if min_score is not None and not (math.isfinite(min_score) and 0.0 <= min_score <= 1.0):
        return _ERR_SCORE, None
    cleaned: list[str] | None = None
    if prompts is not None:
        cleaned = [_clean(prompt) or "" for prompt in prompts]
        if not cleaned:
            return _ERR_PROMPTS, None
        if not all(cleaned):
            return _ERR_TEXT, None
    return None, cleaned


def _check_folder(folder: str) -> str | None:
    """The fixed-text problem with a folder name, using the same check as `result_folder`."""
    problem = None
    try:
        validate_folder_segment(folder)
    except LayoutError:
        problem = _ERR_FOLDER
    return problem


def _rules(conn: psycopg.Connection) -> list[CategoryRule]:
    rows = conn.execute(
        "select id, axis, name, folder, min_score, branch, parent_id from categories"
    ).fetchall()
    return [CategoryRule(*row) for row in rows]


def _sibling_clash(
    rules: list[CategoryRule], axis: str, parent_id: int | None, folder: str, own_id: int
) -> bool:
    """FOP-002.D4: siblings differ by folder ignoring case (the unique index backs this)."""
    return any(
        rule.id != own_id
        and rule.axis == axis
        and rule.parent_id == parent_id
        and rule.folder.lower() == folder.lower()
        for rule in rules
    )


def _run(config_path: str | None, work) -> None:
    """Open a transaction, run `work(config, conn)` -> problem text or None, and report it."""
    config, conn = _open(config_path)
    problem = None
    code = 2
    try:
        with conn:  # commits on success, rolls back on error or when `work` returns a problem
            problem = work(config, conn)
            if problem is not None:
                conn.rollback()
    except psycopg.errors.UniqueViolation:
        problem = _ERR_EXISTS
    except psycopg.Error:
        problem, code = _ERR_DB, 1
    finally:
        conn.close()
    if problem is not None:
        raise _fail(problem, code)


@categories_app.command("sync-folders")
def sync_folders_command(config_path: ConfigOption = None) -> None:
    """Create the empty category folders under results_root (FOP-002.2, R-CLS-7).

    Always creates, whatever `folders.auto_create` says: that key only governs whether M7's
    sort runs this itself. Only creates directories; none is ever removed or renamed.
    """
    config, conn = _open(config_path)
    problem = None
    rules: list[CategoryRule] = []
    filed: list[FiledPair] = []
    try:
        with conn:
            rules = _rules(conn)
            rows = conn.execute(
                "select topic, format, branch from files where status = 'filed'"
            ).fetchall()
            filed = [FiledPair(*row) for row in rows]
    except psycopg.Error:
        problem = _ERR_DB
    finally:
        conn.close()
    if problem is not None:
        raise _fail(problem, 1)
    created = 0
    try:
        created = sync_folders(config.paths, rules, filed, config.folders, config.nsfw).created
    except FolderSyncError as error:  # fixed text, or category names; never a path
        problem = str(error)
    if problem is not None:
        raise _fail(problem)
    typer.echo(f"created {created} folders")


@categories_app.command("add")
def add_category(
    name: Annotated[str, typer.Argument(help="Category name, unique on its axis.")],
    axis: Annotated[str, typer.Option("--axis", help="format or topic.")],
    folder: Annotated[str, typer.Option("--folder", help="Result folder name.")],
    prompt: Annotated[list[str] | None, typer.Option("--prompt", help=_UNUSED_HELP)] = None,
    min_score: Annotated[float | None, typer.Option("--min-score", help=_UNUSED_HELP)] = None,
    branch: Annotated[str, typer.Option("--branch", help="any, safe or nsfw.")] = "any",
    parent: Annotated[str | None, typer.Option("--parent", help="Parent name, same axis.")] = None,
    config_path: ConfigOption = None,
) -> None:
    """Add a category. It applies to the next classify (CLI-004.D2)."""
    problem, prompts = _check_common(axis, branch, min_score, prompt)
    clean_name = _clean(name)
    clean_parent = _clean(parent) if parent is not None else None
    if problem is None and (clean_name is None or (parent is not None and clean_parent is None)):
        problem = _ERR_TEXT
    if problem is None and clean_name is not None and clean_name.lower() == UNSORTED:
        problem = _ERR_RESERVED
    if problem is None:
        problem = _check_folder(folder)
    if problem is not None:
        raise _fail(problem)
    assert clean_name is not None

    def work(config: Config, conn: psycopg.Connection) -> str | None:
        rules = _rules(conn)
        parent_id = None
        if clean_parent is not None:
            found = [r for r in rules if r.axis == axis and r.name == clean_parent]
            if not found:
                return _ERR_PARENT_MISSING
            parent_id = found[0].id
        if _sibling_clash(rules, axis, parent_id, folder, own_id=-1):
            return _ERR_SIBLING
        candidate = CategoryRule(-1, axis, clean_name, folder, min_score, branch, parent_id)
        rules_problem = None
        try:
            validate_rules([*rules, candidate], None)  # CLS-004.D7
        except ClassifyRulesError as error:  # fixed text, no value in it
            rules_problem = str(error)
        if rules_problem is not None:
            return rules_problem
        row = conn.execute(
            "insert into categories (axis, name, folder, min_score, branch, parent_id) "
            "values (%s, %s, %s, %s, %s, %s) returning id",
            (axis, clean_name, folder, min_score, branch, parent_id),
        ).fetchone()
        assert row is not None
        for position, text in enumerate(prompts or []):
            conn.execute(
                "insert into category_prompts (category_id, position, prompt) values (%s, %s, %s)",
                (row[0], position, text),
            )
        return None

    _run(config_path, work)
    typer.echo(f"added {axis} category {clean_name}")


@categories_app.command("edit")
def edit_category(
    name: Annotated[str, typer.Argument(help="The category to edit.")],
    axis: Annotated[str, typer.Option("--axis", help="format or topic.")],
    folder: Annotated[str | None, typer.Option("--folder", help="New result folder name.")] = None,
    prompt: Annotated[
        list[str] | None,
        typer.Option("--prompt", help=_UNUSED_HELP),
    ] = None,
    min_score: Annotated[float | None, typer.Option("--min-score", help=_UNUSED_HELP)] = None,
    reset_min_score: Annotated[bool, typer.Option("--reset-min-score", help=_UNUSED_HELP)] = False,
    branch: Annotated[str | None, typer.Option("--branch", help="any, safe or nsfw.")] = None,
    config_path: ConfigOption = None,
) -> None:
    """Edit a category's folder, prompts, min_score or branch (CLI-004.D2: next classify)."""
    problem, prompts = _check_common(axis, branch, min_score, prompt)
    clean_name = _clean(name)
    if problem is None and clean_name is None:
        problem = _ERR_TEXT
    if problem is None and clean_name is not None and clean_name.lower() == UNSORTED:
        problem = _ERR_RESERVED
    if problem is None and min_score is not None and reset_min_score:
        problem = _ERR_SCORE_BOTH
    nothing = (
        folder is None
        and prompts is None
        and min_score is None
        and not reset_min_score
        and branch is None
    )
    if problem is None and nothing:
        problem = _ERR_NOTHING
    if problem is None and folder is not None:
        problem = _check_folder(folder)
    if problem is not None:
        raise _fail(problem)
    assert clean_name is not None

    def work(config: Config, conn: psycopg.Connection) -> str | None:
        rules = _rules(conn)
        found = [r for r in rules if r.axis == axis and r.name == clean_name]
        if not found:
            return _ERR_MISSING
        current = found[0]
        new_folder = current.folder if folder is None else folder
        new_branch = current.branch if branch is None else branch
        new_score = min_score if min_score is not None else current.min_score
        if reset_min_score:
            new_score = None
        if _sibling_clash(rules, axis, current.parent_id, new_folder, own_id=current.id):
            return _ERR_SIBLING
        changed = CategoryRule(
            current.id, axis, current.name, new_folder, new_score, new_branch, current.parent_id
        )
        others = [r for r in rules if r.id != current.id]
        rules_problem = None
        try:
            validate_rules([*others, changed], None)  # CLS-004.D7
        except ClassifyRulesError as error:  # fixed text, no value in it
            rules_problem = str(error)
        if rules_problem is not None:
            return rules_problem
        conn.execute(
            "update categories set folder = %s, min_score = %s, branch = %s where id = %s",
            (new_folder, new_score, new_branch, current.id),
        )
        if prompts is not None:
            conn.execute("delete from category_prompts where category_id = %s", (current.id,))
            for position, text in enumerate(prompts):
                conn.execute(
                    "insert into category_prompts (category_id, position, prompt) "
                    "values (%s, %s, %s)",
                    (current.id, position, text),
                )
        return None

    _run(config_path, work)
    typer.echo(f"edited {axis} category {clean_name}")


@categories_app.command("remove")
def remove_category(
    name: Annotated[str, typer.Argument(help="The category to remove.")],
    axis: Annotated[str, typer.Option("--axis", help="format or topic.")],
    config_path: ConfigOption = None,
) -> None:
    """Remove a category and its prompts. Files and folders are never touched (R-CLS-7)."""
    problem, _ = _check_common(axis, None, None, None)
    clean_name = _clean(name)
    if problem is None and clean_name is None:
        problem = _ERR_TEXT
    if problem is None and clean_name is not None and clean_name.lower() == UNSORTED:
        problem = _ERR_RESERVED
    if problem is not None:
        raise _fail(problem)
    assert clean_name is not None

    def work(config: Config, conn: psycopg.Connection) -> str | None:
        rules = _rules(conn)
        found = [r for r in rules if r.axis == axis and r.name == clean_name]
        if not found:
            return _ERR_MISSING
        if any(r.parent_id == found[0].id for r in rules):  # CLI-004.D1
            return _ERR_CHILDREN
        # The files table keeps its text value (DB-003.D1); only configuration rows go.
        conn.execute("delete from category_prompts where category_id = %s", (found[0].id,))
        conn.execute("delete from categories where id = %s", (found[0].id,))
        return None

    _run(config_path, work)
    typer.echo(f"removed {axis} category {clean_name}")
