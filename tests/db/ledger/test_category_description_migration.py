"""DB-006.1 acceptance: migration 0006 adds `categories.description` and `files.nsfw_traces`.

Isolated like test_nsfw_level_migration.py: a throwaway schema per test, dropped with `cascade`.
Every value is synthetic (the golden seeds quote DESIGN §4.3, which is public).
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

from classifier.db.models import Category
from classifier.db.url import to_sqlalchemy_url
from tests.db.db_support import require_db_dsn

INI = Path(__file__).resolve().parents[3] / "classifier" / "db" / "alembic.ini"
HASH = "a" * 64
# DESIGN §4.3's generic descriptions, typed out from its two tables (bold markers dropped,
# DB-006.D1), not imported from migration 0006, so a seed that drifts from the spec fails
# (DB-008.1).
GOLDEN: dict[tuple[str, str], str] = {
    ("format", "photos"): (
        "a real-world photograph taken with a camera or phone camera, not a capture of a screen"
    ),
    ("format", "game-screenshots"): (
        "a capture taken inside a video game: the game world, a game HUD, or a menu rendered by "
        "the game, on any platform"
    ),
    ("format", "screenshots"): (
        "a capture of a computer or phone screen showing an app, website, chat, social media post "
        "or OS interface, even when its content is about games"
    ),
    ("format", "memes"): (
        "a joke: an image made or shared as a joke, in any style (a captioned picture, a meme "
        "template, a funny drawing or photo, an edited image)"
    ),
    ("format", "artwork"): (
        "a drawing, digital illustration, anime or cartoon art, concept art, 3D render or "
        "abstract graphic"
    ),
    ("format", "documents"): "a scanned or photographed document, receipt or form",
    ("topic", "videogames"): "video games: game captures, game characters, game interfaces",
    ("topic", "anime"): "anime characters or manga-style art",
    ("topic", "cartoons"): "western cartoon characters or comics",
    ("topic", "pc-equipment"): "computer cases, PC hardware and components",
    ("topic", "animals"): "animals, pets",
    ("topic", "people"): "real people, faces, groups of people",
    ("topic", "landscapes"): "landscapes, beaches, cityscapes, views",
    ("topic", "music"): "music: song lists, music players, artists' albums",
    ("topic", "tv-shows"): "stills or scenes from TV shows or films",
    ("topic", "software"): "software: code editors, app screens, programs",
    ("topic", "memes"): (
        "a joke: the image's meaning is a joke, humor or irony (its meaning, not its form)"
    ),
    ("topic", "documents"): "documents, receipts, forms, lists of text, as its subject",
}
INSERT_FILE = (
    "insert into files (source_hash, short_hash, source_path, source_mtime, ext) "
    "values (%s, 'aaaaaaaa', '/source/x', now(), 'png')"
)
INSERT_CATEGORY = (
    "insert into categories (axis, name, folder, description) "
    "values ('topic', 'qorvex', 'Qorvex', %s)"
)
SELECT_QORVEX = "select description from categories where name = 'qorvex'"


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
    """An autocommit connection on a schema at head."""
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        yield c


def _rows(schema: str, sql: str) -> list[tuple]:
    with psycopg.connect(require_db_dsn()) as c:
        c.execute(f'set search_path to "{schema}", public')
        return c.execute(sql).fetchall()


def _column(schema: str, table: str, column: str) -> list[tuple]:
    return _rows(
        schema,
        "select data_type, is_nullable = 'YES', column_default from information_schema.columns "
        f"where table_schema = '{schema}' and table_name = '{table}' and column_name = '{column}'",
    )


def _check_names(schema: str, table: str) -> list[str]:
    return [
        name
        for (name,) in _rows(
            schema,
            "select conname from pg_constraint "
            f"where conrelid = '\"{schema}\".{table}'::regclass and contype = 'c' order by 1",
        )
    ]


def test_0006_is_the_single_head_after_0005(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert len(script.get_heads()) == 1  # later migrations extend the chain
    assert script.get_revision("0006").down_revision == "0005"


def test_upgrade_adds_both_columns_and_the_check(alembic_cfg: Config, schema: str) -> None:
    command.upgrade(alembic_cfg, "0005")
    assert _column(schema, "categories", "description") == []
    assert _column(schema, "files", "nsfw_traces") == []
    assert "categories_description" not in _check_names(schema, "categories")

    command.upgrade(alembic_cfg, "0006")
    assert _column(schema, "categories", "description") == [("text", True, None)]
    assert _column(schema, "files", "nsfw_traces") == [("boolean", True, None)]
    assert "categories_description" in _check_names(schema, "categories")
    assert _rows(schema, "select version_num from alembic_version") == [("0006",)]


def test_every_default_category_is_seeded(conn: psycopg.Connection) -> None:
    rows = conn.execute("select axis, name, description from categories").fetchall()
    described = {(axis, name): d for axis, name, d in rows if d is not None}
    assert len(GOLDEN) == 18
    # Exact both ways: no seed missing, none changed, nothing extra described.
    assert described == GOLDEN
    for description in GOLDEN.values():
        assert description == description.strip()
        assert "**" not in description  # the bold markers are gone
        assert len(description) <= 200
    # The same name differs per axis.
    assert GOLDEN[("format", "memes")] != GOLDEN[("topic", "memes")]
    assert GOLDEN[("format", "documents")] != GOLDEN[("topic", "documents")]


def test_unsorted_and_user_added_categories_stay_null(conn: psycopg.Connection) -> None:
    unsorted = conn.execute(
        "select description from categories where axis = 'format' and name = 'unsorted'"
    ).fetchall()
    assert unsorted in ([(None,)], [])
    conn.execute(INSERT_CATEGORY, (None,))
    assert conn.execute(SELECT_QORVEX).fetchall() == [(None,)]


@pytest.mark.parametrize("value", ["a" * 200, "x", "a joke: Zhyndel"])
def test_the_check_accepts_valid_values(conn: psycopg.Connection, value: str) -> None:
    conn.execute(INSERT_CATEGORY, (value,))
    assert conn.execute(SELECT_QORVEX).fetchall() == [(value,)]


@pytest.mark.parametrize(
    "value",
    [
        "a" * 201,
        "",
        "   ",
        " \t ",
        "two\nlines",
        "two\r\nlines",
        "tab\there",
        "bell\x07",
        "del\x7f",
    ],
)
def test_the_check_refuses_bad_values(conn: psycopg.Connection, value: str) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(INSERT_CATEGORY, (value,))
    conn.execute(INSERT_CATEGORY, (None,))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("update categories set description = %s where name = 'qorvex'", (value,))
    assert conn.execute(SELECT_QORVEX).fetchall() == [(None,)]


def test_a_description_can_be_set_back_to_null(conn: psycopg.Connection) -> None:
    conn.execute(INSERT_CATEGORY, ("a joke: Zhyndel",))
    conn.execute("update categories set description = null where name = 'qorvex'")
    assert conn.execute(SELECT_QORVEX).fetchall() == [(None,)]


def test_nsfw_traces_reads_null_and_takes_a_boolean(conn: psycopg.Connection) -> None:
    conn.execute(INSERT_FILE, (HASH,))
    assert conn.execute("select nsfw_traces from files").fetchone() == (None,)
    for value in (True, False, None):
        conn.execute("update files set nsfw_traces = %s", (value,))
        assert conn.execute("select nsfw_traces from files").fetchone() == (value,)


def test_the_description_never_shows_in_a_repr() -> None:
    secret = "Qorvex-private-wording-7f3a"
    category = Category(id=7, axis="topic", name="zhyndel", folder="Zhyndel", description=secret)
    assert category.description == secret  # the planted value is really on the object
    assert secret not in repr(category)
    assert secret not in str(category)


def test_downgrade_to_0005_drops_only_what_0006_added_and_back(
    alembic_cfg: Config, schema: str
) -> None:
    command.upgrade(alembic_cfg, "head")
    with psycopg.connect(require_db_dsn(), autocommit=True) as c:
        c.execute(f'set search_path to "{schema}", public')
        c.execute(INSERT_FILE, (HASH,))
        c.execute("update files set format = 'qorvex', nsfw_level = 'safe', nsfw_traces = true")

    command.downgrade(alembic_cfg, "0005")
    assert _column(schema, "categories", "description") == []
    assert _column(schema, "files", "nsfw_traces") == []
    assert "categories_description" not in _check_names(schema, "categories")
    # Only what 0006 added is gone: the row and its other columns survive.
    assert _rows(schema, "select source_hash, format, nsfw_level from files") == [
        (HASH, "qorvex", "safe")
    ]
    assert _rows(schema, "select count(*) > 0 from categories") == [(True,)]
    assert _rows(schema, "select version_num from alembic_version") == [("0005",)]

    command.upgrade(alembic_cfg, "head")
    assert _rows(schema, "select nsfw_traces from files") == [(None,)]  # the old value is gone
    assert _rows(schema, "select description from categories where name = 'photos'") != [(None,)]
