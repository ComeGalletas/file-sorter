"""CLI-004.1 acceptance: `classifier categories list|add|edit|remove` (R-CLS-7, R-CLS-4, R-CLS-6).

Each module gets a throwaway schema at Alembic head and points `DB_DSN` at it, so the command's
own connection sees committed rows and nothing leaks into other db tests. Every name, folder
and prompt is a synthetic coinage; assertions are on those rows, not on the seed.
"""

import uuid
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import quote

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from classifier.cli import app
from classifier.cli.categories import _check_folder
from classifier.config import load_config
from classifier.db.url import to_sqlalchemy_url
from classifier.fileops.layout import LayoutError, result_folder
from tests.db.db_support import require_db_dsn

ROOT = Path(__file__).resolve().parents[3]
INI = ROOT / "classifier" / "db" / "alembic.ini"
CONFIG = str(ROOT / "config.yaml")
runner = CliRunner()


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


@pytest.fixture
def cli(schema_dsn: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Point the command at the schema; remove every row a test added, even on failure."""
    monkeypatch.setenv("DB_DSN", schema_dsn)
    seed = _snapshot(schema_dsn)
    yield
    with psycopg.connect(schema_dsn) as conn:
        keep = seed or [0]
        conn.execute("delete from category_prompts where category_id <> all(%s)", (keep,))
        conn.execute("update categories set parent_id = null where id <> all(%s)", (keep,))
        conn.execute("delete from categories where id <> all(%s)", (keep,))
    assert _snapshot(schema_dsn) == seed


def _snapshot(dsn: str) -> list[int]:
    with psycopg.connect(dsn) as conn:
        return [r[0] for r in conn.execute("select id from categories order by id")]


def run(*args: str):
    return runner.invoke(app, ["categories", *args, "--config", CONFIG])


def test_list_shows_the_columns_and_the_seeded_unsorted(cli: None) -> None:
    result = run("list")
    assert result.exit_code == 0
    lines = result.output.splitlines()
    assert lines[0] == "axis\tname\tfolder\tmin_score\tbranch\tparent\tprompts"
    unsorted = [ln for ln in lines if ln.startswith("format\tunsorted\t")]
    assert unsorted == ["format\tunsorted\tUnsorted\taxis default\tany\t-\t0"]


def _rows(dsn: str, sql: str, *params: object) -> list[tuple]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, params).fetchall()


def add(*args: str):
    return run("add", *args)


def test_add_creates_the_category_and_its_prompts_in_order(cli: None, schema_dsn: str) -> None:
    result = add(
        "Qorvex", "--axis", "topic", "--folder", "Qorvex Dir", "--prompt", "a qorvex",
        "--prompt", "two qorvex", "--min-score", "0.4", "--branch", "safe",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "added topic category Qorvex"
    assert _rows(
        schema_dsn,
        "select c.folder, c.min_score, c.branch, p.position, p.prompt from categories c "
        "join category_prompts p on p.category_id = c.id where c.name = 'Qorvex' order by 4",
    ) == [
        ("Qorvex Dir", pytest.approx(0.4), "safe", 0, "a qorvex"),
        ("Qorvex Dir", pytest.approx(0.4), "safe", 1, "two qorvex"),
    ]  # noqa: E501
    listed = run("list").output
    assert "topic\tQorvex\tQorvex Dir\t0.4\tsafe\t-\t2" in listed


def test_add_with_a_parent_on_the_same_axis(cli: None) -> None:
    assert add("Zhyndel", "--axis", "topic", "--folder", "Zh", "--prompt", "p").exit_code == 0
    result = add(
        "Zhyndel Kid", "--axis", "topic", "--folder", "Kid", "--prompt", "p", "--parent", "Zhyndel"
    )
    assert result.exit_code == 0, result.output
    assert "topic\tZhyndel Kid\tKid\taxis default\tany\tZhyndel\t1" in run("list").output


def _fails(result, text: str) -> None:
    assert result.exit_code == 2
    assert result.output.strip() == f"error: {text}"
    assert result.exception is None or isinstance(result.exception, SystemExit)


@pytest.mark.parametrize(
    ("args", "text"),
    [
        (["--axis", "mood", "--folder", "Q", "--prompt", "p"], "--axis must be format or topic"),
        (["--axis", "topic", "--folder", "Q", "--prompt", "p", "--branch", "x"],
         "--branch must be any, safe or nsfw"),
        (["--axis", "topic", "--folder", "Q", "--prompt", "p", "--min-score", "1.5"],
         "--min-score must be a number from 0 to 1"),
        (["--axis", "topic", "--folder", "Q", "--prompt", "p", "--min-score", "nan"],
         "--min-score must be a number from 0 to 1"),
        (["--axis", "topic", "--folder", "Q"], "at least one --prompt is required"),
        (["--axis", "topic", "--folder", "Q", "--prompt", "  "],
         "a name or prompt is empty, has a control character or is not valid text"),
        (["--axis", "topic", "--folder", "a/b", "--prompt", "p"], "invalid folder name"),
        (["--axis", "topic", "--folder", "nul", "--prompt", "p"], "invalid folder name"),
        (["--axis", "topic", "--folder", "Q", "--prompt", "p", "--parent", "Nopeq"],
         "the parent category does not exist on that axis"),
    ],
)  # fmt: skip
def test_add_refuses_bad_input_with_fixed_text(cli: None, args: list[str], text: str) -> None:
    _fails(add("Qorvex", *args), text)


def test_add_refuses_unsorted_and_lone_surrogates(cli: None) -> None:
    _fails(
        add("Unsorted", "--axis", "topic", "--folder", "Q", "--prompt", "p"),
        "the unsorted category is protected",
    )
    result = add("Qor\ud800vex", "--axis", "topic", "--folder", "Q", "--prompt", "p")
    _fails(result, "a name or prompt is empty, has a control character or is not valid text")
    assert "\ud800" not in result.output


def test_add_refuses_a_duplicate_name_and_a_sibling_folder_ignoring_case(cli: None) -> None:
    assert add("Qorvex", "--axis", "topic", "--folder", "Qv", "--prompt", "p").exit_code == 0
    _fails(
        add("Qorvex", "--axis", "topic", "--folder", "Other", "--prompt", "p"),
        "duplicate category name on one axis",
    )
    _fails(
        add("Zhyndel", "--axis", "topic", "--folder", "qV", "--prompt", "p"),
        "a sibling category already uses that folder (compared ignoring case)",
    )
    # the same folder is fine on the other axis
    assert add("Zhyndel", "--axis", "format", "--folder", "Qv", "--prompt", "p").exit_code == 0


def test_add_refuses_a_parent_on_the_other_axis(cli: None) -> None:
    assert add("Qorvex", "--axis", "topic", "--folder", "Qv", "--prompt", "p").exit_code == 0
    _fails(
        add("Zhyndel", "--axis", "format", "--folder", "Z", "--prompt", "p", "--parent", "Qorvex"),
        "the parent category does not exist on that axis",
    )


@pytest.mark.parametrize(
    "name",
    ["Qorvex", "a b", ".", "..", "", "a/b", "a\b", "a:b", "x.", "x ", "NUL", "com1.txt", "a?"],
)
def test_a_folder_the_cli_accepts_is_one_result_folder_accepts(cli: None, name: str) -> None:
    folders = load_config(CONFIG).folders
    try:
        result_folder(
            branch="safe", topic_path=[], format_folder=name, animated=False,
            folders=folders, nsfw_root="Adult",
        )  # fmt: skip
        accepted = True
    except LayoutError:
        accepted = False
    assert (_check_folder(name) is None) == accepted
