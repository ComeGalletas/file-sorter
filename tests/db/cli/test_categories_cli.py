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
import typer
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url
from typer.testing import CliRunner

from classifier.cli import app
from classifier.cli.categories import _check_folder, add_category
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
    assert lines[0] == ("axis\tname\tfolder\tmin_score(unused)\tbranch\tparent\tprompts(unused)")
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


def test_add_without_a_prompt_succeeds_and_stores_none(cli: None, schema_dsn: str) -> None:
    result = add("Qorvex", "--axis", "topic", "--folder", "Qv")  # CLI-006.1
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "added topic category Qorvex"
    assert _rows(
        schema_dsn,
        "select count(*) from category_prompts p join categories c on c.id = p.category_id "
        "where c.name = 'Qorvex'",
    ) == [(0,)]
    assert "topic\tQorvex\tQv\taxis default\tany\t-\t0" in run("list").output


def test_help_marks_prompt_and_min_score_unused(cli: None) -> None:
    for verb in ("add", "edit"):
        text = " ".join(run(verb, "--help").output.split())
        assert "Unused on the VLM path (CLS-004.D7)" in text
        assert "DOC-009.D3" in text


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


def _make(name: str, axis: str = "topic", folder: str | None = None, *extra: str) -> None:
    result = add(name, "--axis", axis, "--folder", folder or name, "--prompt", f"p {name}", *extra)
    assert result.exit_code == 0, result.output


def edit(name: str, *args: str, axis: str = "topic"):
    return run("edit", name, "--axis", axis, *args)


def test_edit_changes_folder_prompts_score_and_branch(cli: None, schema_dsn: str) -> None:
    _make("Qorvex")
    result = edit(
        "Qorvex", "--folder", "Qv2", "--prompt", "one", "--prompt", "two", "--prompt", "three",
        "--min-score", "0.55", "--branch", "nsfw",
    )  # fmt: skip
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "edited topic category Qorvex"
    assert "topic\tQorvex\tQv2\t0.55\tnsfw\t-\t3" in run("list").output
    assert _rows(
        schema_dsn,
        "select p.position, p.prompt from category_prompts p join categories c "
        "on c.id = p.category_id where c.name = 'Qorvex' order by 1",
    ) == [(0, "one"), (1, "two"), (2, "three")]


def test_edit_can_reset_min_score_and_keeps_other_fields(cli: None) -> None:
    _make("Qorvex", "topic", "Qv", "--min-score", "0.3")
    assert edit("Qorvex", "--reset-min-score").exit_code == 0
    assert "topic\tQorvex\tQv\taxis default\tany\t-\t1" in run("list").output


@pytest.mark.parametrize(
    ("args", "text"),
    [
        ([], "nothing to change: pass --folder, --prompt, --min-score or --branch"),
        (["--min-score", "0.2", "--reset-min-score"],
         "--min-score and --reset-min-score cannot be used together"),
        (["--folder", "a/b"], "invalid folder name"),
        (["--branch", "x"], "--branch must be any, safe or nsfw"),
        (["--min-score", "2"], "--min-score must be a number from 0 to 1"),
        (["--prompt", ""],
         "a name or prompt is empty, has a control character or is not valid text"),
    ],
)  # fmt: skip
def test_edit_refuses_bad_input_with_fixed_text(cli: None, args: list[str], text: str) -> None:
    _make("Qorvex")
    _fails(edit("Qorvex", *args), text)


def test_edit_refuses_unknown_unsorted_and_sibling_folder_clash(cli: None) -> None:
    _make("Qorvex", "topic", "Qv")
    _make("Zhyndel", "topic", "Zh")
    _fails(edit("Nopeq", "--folder", "X"), "no such category on this axis")
    _fails(edit("unsorted", "--prompt", "p", axis="format"), "the unsorted category is protected")
    _fails(
        edit("Zhyndel", "--folder", "QV"),
        "a sibling category already uses that folder (compared ignoring case)",
    )
    assert edit("Zhyndel", "--folder", "ZH").exit_code == 0  # its own folder, other case


def test_remove_deletes_the_category_and_its_prompts_only(cli: None, schema_dsn: str) -> None:
    _make("Qorvex")
    before = _rows(schema_dsn, "select count(*) from category_prompts")[0][0]
    result = run("remove", "Qorvex", "--axis", "topic")
    assert result.exit_code == 0, result.output
    assert result.output.strip() == "removed topic category Qorvex"
    assert "Qorvex" not in run("list").output
    assert _rows(schema_dsn, "select count(*) from category_prompts")[0][0] == before - 1


def test_remove_refuses_a_parent_unsorted_and_an_unknown_name(cli: None) -> None:
    _make("Qorvex")
    _make("Zhyndel", "topic", "Zh", "--parent", "Qorvex")
    _fails(
        run("remove", "Qorvex", "--axis", "topic"),
        "the category has children; remove or move them first",
    )
    _fails(run("remove", "unsorted", "--axis", "format"), "the unsorted category is protected")
    _fails(run("remove", "Nopeq", "--axis", "topic"), "no such category on this axis")
    assert run("remove", "Zhyndel", "--axis", "topic").exit_code == 0
    assert run("remove", "Qorvex", "--axis", "topic").exit_code == 0


def test_remove_leaves_files_with_the_category_name(cli: None, schema_dsn: str) -> None:
    """R-CLS-7 / DB-003.D1: `files.topic` is a name with no FK, so a removed one stays put."""
    _make("Qorvex")
    with psycopg.connect(schema_dsn) as conn:
        conn.execute(
            "insert into files (source_hash, short_hash, source_path, source_mtime, ext, topic) "
            "values (%s, 'bbbbbbbb', '/source/x', now(), 'png', 'Qorvex')",
            ("b" * 64,),
        )
    try:
        assert run("remove", "Qorvex", "--axis", "topic").exit_code == 0
        assert _rows(schema_dsn, "select topic from files where short_hash = 'bbbbbbbb'") == [
            ("Qorvex",)
        ]
    finally:
        with psycopg.connect(schema_dsn) as conn:
            conn.execute("delete from files where short_hash = 'bbbbbbbb'")


def test_errors_never_echo_typed_values_and_are_unchained(cli: None) -> None:
    secret = "zzsecretzz"
    result = add(secret, "--axis", "topic", "--folder", "a/" + secret, "--prompt", secret)
    assert result.exit_code == 2
    assert secret not in result.output
    # Called directly, the Exit the command raises has no cause or context.
    with pytest.raises(typer.Exit) as raised:
        add_category(secret, "topic", "a/" + secret, [secret], None, "any", None, CONFIG)
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_a_database_failure_is_fixed_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DB_DSN", "postgresql://nobody:pw-qorvex@127.0.0.1:1/none")
    result = run("list")
    assert result.exit_code == 1
    assert result.output.strip() == "error: database error, see the db service logs"
    assert "qorvex" not in result.output


def test_a_missing_config_is_fixed_text(cli: None) -> None:
    result = runner.invoke(app, ["categories", "list", "--config", "/nope/qorvex.yaml"])
    assert result.exit_code == 2
    assert "qorvex" not in result.output
