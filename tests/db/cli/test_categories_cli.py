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
from classifier.db.url import to_sqlalchemy_url
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
