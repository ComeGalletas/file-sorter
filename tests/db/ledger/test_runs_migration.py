"""DB-007.1 acceptance: migration 0007 adds `runs`; `runlock` holds one session-level lock.

Isolated like test_sanitize_log_migration.py: a throwaway schema per test, dropped with
`cascade`. Every value is synthetic.
"""

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from classifier.db.models import RUN_KINDS, RUN_STATES, Run
from classifier.db.runlock import RUN_LOCK_KEY, release_run_lock, try_run_lock
from classifier.db.url import to_sqlalchemy_url
from tests.db.db_support import require_db_dsn

INI = Path(__file__).resolve().parents[3] / "classifier" / "db" / "alembic.ini"
RUN_COLUMNS = {
    "id": ("bigint", False), "kind": ("text", False), "state": ("text", False),
    "started_at": ("timestamp with time zone", False),
    "finished_at": ("timestamp with time zone", True),
    "counts": ("jsonb", False), "error": ("text", True),
}  # fmt: skip
CHECKS = {
    "runs_kind", "runs_state", "runs_counts_object", "runs_error_code",
    "runs_finished_iff_done", "runs_error_only_failed", "runs_finished_after_start",
}  # fmt: skip
INSERT = (
    "insert into runs (kind, state, started_at, finished_at, counts, error) "
    "values (%s, %s, %s, %s, %s, %s)"
)
# Pinned, so a refusal is always the CHECK the case names, never a clock race.
START = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
END = START + timedelta(minutes=1)


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
    # configparser interpolation: a literal % must be doubled.
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


def _columns(c: psycopg.Connection, schema: str) -> dict[str, tuple[str, bool]]:
    rows = c.execute(
        "select column_name, data_type, is_nullable = 'YES' from information_schema.columns "
        "where table_schema = %s and table_name = 'runs'",
        (schema,),
    ).fetchall()
    return {name: (kind, nullable) for name, kind, nullable in rows}


def test_0007_extends_0006_and_is_the_single_head(alembic_cfg: Config) -> None:
    script = ScriptDirectory.from_config(alembic_cfg)
    assert script.get_heads() == ["0007"]
    assert script.get_revision("0007").down_revision == "0006"


def test_upgrade_adds_the_table(conn: psycopg.Connection, schema: str) -> None:
    assert _columns(conn, schema) == RUN_COLUMNS
    identity = conn.execute(
        "select is_identity, identity_generation from information_schema.columns "
        "where table_schema = %s and table_name = 'runs' and column_name = 'id'",
        (schema,),
    ).fetchone()
    assert identity == ("YES", "ALWAYS")
    checks = conn.execute(
        "select conname from pg_constraint where conrelid = 'runs'::regclass and contype = 'c'"
    ).fetchall()
    assert {name for (name,) in checks} == CHECKS
    assert conn.execute("select version_num from alembic_version").fetchall() == [("0007",)]


def test_the_orm_mirrors_the_checks() -> None:
    names = {c.name for c in Run.__table__.constraints if c.name and c.name.startswith("runs_")}
    assert names == CHECKS
    assert RUN_KINDS == ("dry_run", "sort", "watch", "reclassify")
    assert RUN_STATES == ("running", "finished", "failed")


@pytest.mark.parametrize("kind", RUN_KINDS)
def test_a_running_row_takes_the_defaults(conn: psycopg.Connection, kind: str) -> None:
    conn.execute("insert into runs (kind) values (%s)", (kind,))
    row = conn.execute(
        "select id, state, started_at is not null, finished_at, counts, error from runs"
    ).fetchone()
    assert row is not None and row[0] >= 1
    assert row[1:] == ("running", True, None, {}, None)


@pytest.mark.parametrize(
    ("state", "finished", "counts", "error"),
    [
        ("running", False, '{"ingest": 3}', None),
        ("finished", True, '{"ingest": 3, "classify": 2}', None),
        ("failed", True, "{}", "db_unavailable"),
        ("failed", True, "{}", None),
    ],
)
def test_a_consistent_row_is_accepted(
    conn: psycopg.Connection, state: str, finished: bool, counts: str, error: str | None
) -> None:
    conn.execute(INSERT, ("dry_run", state, START, END if finished else None, counts, error))
    assert conn.execute("select state, error from runs").fetchall() == [(state, error)]


@pytest.mark.parametrize(
    ("kind", "state", "finished", "counts", "error", "check"),
    [
        ("Qorvex", "running", False, "{}", None, "runs_kind"),
        ("DRY_RUN", "running", False, "{}", None, "runs_kind"),
        ("dry_run", "zhyndel", True, "{}", None, "runs_state"),
        ("dry_run", "running", True, "{}", None, "runs_finished_iff_done"),
        ("dry_run", "finished", False, "{}", None, "runs_finished_iff_done"),
        ("dry_run", "failed", False, "{}", "db_unavailable", "runs_finished_iff_done"),
        ("dry_run", "finished", True, "{}", "db_unavailable", "runs_error_only_failed"),
        ("dry_run", "running", False, "{}", "db_unavailable", "runs_error_only_failed"),
        ("dry_run", "failed", True, "{}", "/source/qorvex.png", "runs_error_code"),  # path-like
        ("dry_run", "failed", True, "{}", "Qorvex Zhyndel", "runs_error_code"),  # free text
        ("dry_run", "failed", True, "{}", "has space", "runs_error_code"),
        ("dry_run", "failed", True, "{}", "", "runs_error_code"),
        ("dry_run", "failed", True, "{}", "x" * 65, "runs_error_code"),
        ("dry_run", "running", False, "[]", None, "runs_counts_object"),
        ("dry_run", "running", False, "3", None, "runs_counts_object"),
    ],
)
def test_the_checks_refuse_a_bad_row(
    conn: psycopg.Connection,
    kind: str,
    state: str,
    finished: bool,
    counts: str,
    error: str | None,
    check: str,
) -> None:
    with pytest.raises(psycopg.errors.CheckViolation) as caught:
        conn.execute(INSERT, (kind, state, START, END if finished else None, counts, error))
    assert caught.value.diag.constraint_name == check
    assert conn.execute("select count(*) from runs").fetchone() == (0,)


def test_finished_at_cannot_precede_started_at(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "insert into runs (kind, state, started_at, finished_at) "
            "values ('sort', 'finished', now(), now() - interval '1 second')"
        )


def test_the_id_is_generated_always(conn: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.GeneratedAlways):
        conn.execute("insert into runs (id, kind) values (7, 'sort')")


def test_a_run_round_trips_through_the_orm(engine: Engine) -> None:
    with Session(engine) as session:
        run = Run(kind="dry_run")
        session.add(run)
        session.commit()
        run_id = run.id
        assert run.state == "running" and run.counts == {} and run.finished_at is None

        started = run.started_at  # loads the server default before any change is pending
        run.state = "finished"
        run.finished_at = started
        run.counts = {"ingest": 4, "classify": 4}
        session.commit()

    with Session(engine) as session:
        back = session.get(Run, run_id)
        assert back is not None
        assert (back.kind, back.state, back.counts, back.error) == (
            "dry_run", "finished", {"ingest": 4, "classify": 4}, None,
        )  # fmt: skip
        assert back.finished_at == back.started_at


def test_downgrade_drops_the_table_and_upgrade_restores_it(
    alembic_cfg: Config, conn: psycopg.Connection, schema: str
) -> None:
    conn.execute("insert into runs (kind) values ('watch')")
    command.downgrade(alembic_cfg, "0006")
    assert _columns(conn, schema) == {}
    assert conn.execute("select version_num from alembic_version").fetchall() == [("0006",)]

    command.upgrade(alembic_cfg, "head")
    assert _columns(conn, schema) == RUN_COLUMNS
    assert conn.execute("select count(*) from runs").fetchone() == (0,)


# --- the run lock (DB-007.D1) -------------------------------------------------------------


def test_the_lock_key_is_pinned() -> None:
    assert RUN_LOCK_KEY == 0x667372756E6C636B
    assert -(2**63) <= RUN_LOCK_KEY < 2**63  # fits pg's bigint key


def _held_by_others(conn: psycopg.Connection) -> int:
    """Advisory locks on the run key held by other sessions (bigint keys split in two)."""
    row = conn.execute(
        "select count(*) from pg_locks where locktype = 'advisory' and granted "
        "and classid::bigint = %s and objid::bigint = %s and objsubid = 1 "
        "and pid <> pg_backend_pid()",
        ((RUN_LOCK_KEY >> 32) & 0xFFFFFFFF, RUN_LOCK_KEY & 0xFFFFFFFF),
    ).fetchone()
    return row[0]


def test_only_one_session_holds_the_lock(engine: Engine, conn: psycopg.Connection) -> None:
    with engine.connect() as first, engine.connect() as second:
        assert try_run_lock(first) is True
        assert _held_by_others(conn) == 1
        assert try_run_lock(second) is False

        release_run_lock(first)
        assert _held_by_others(conn) == 0
        assert try_run_lock(second) is True
        release_run_lock(second)


def test_the_lock_survives_a_commit(engine: Engine) -> None:
    """DB-007.D1: session-level, so the per-node commits of a run (PIPE-001.D3) keep it."""
    with engine.connect() as holder, engine.connect() as other:
        assert try_run_lock(holder) is True
        holder.commit()
        holder.execute(select(1))
        holder.rollback()
        assert try_run_lock(other) is False

        release_run_lock(holder)
        holder.commit()
        assert try_run_lock(other) is True
        release_run_lock(other)


def test_the_lock_drops_when_the_holder_closes(engine: Engine) -> None:
    with engine.connect() as other:
        holder = engine.connect()
        assert try_run_lock(holder) is True
        assert try_run_lock(other) is False
        holder.invalidate()  # the session ends, as when the process dies
        holder.close()
        assert try_run_lock(other) is True
        release_run_lock(other)
