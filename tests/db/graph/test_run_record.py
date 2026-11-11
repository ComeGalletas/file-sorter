"""PIPE-002.1 acceptance: a run records itself in `runs` and holds the run lock.

`run` commits, so the module gets its own migrated schema (TST-003.1's `migrated_schema`).
Nodes are stand-ins, except the ingest that proves a planted name stays out of `runs`.
Every value is synthetic.
"""

import logging
from collections.abc import Iterator
from pathlib import Path
from types import MappingProxyType

import psycopg
import pytest
import yaml
from PIL import Image

from classifier.config import Config
from classifier.db.models import RUN_ERRORS
from classifier.db.runlock import RUN_LOCK_KEY
from classifier.graph.ingest import IngestResult
from classifier.graph.nodes import REGISTRY, Node, NodeContext
from classifier.graph.run import RunLockedError, run
from classifier.graph.sanitize import SanitizeResult
from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import migrated_schema

REAL_CONFIG = Path(__file__).resolve().parents[3] / "config.yaml"
INGEST = next(n for n in REGISTRY if n.name == "ingest")
PLANT = "Qorvex"  # a made-up name, planted in a source folder and file name
ROW = "select kind, state, finished_at >= started_at, counts, error from runs order by id"


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    with migrated_schema(require_db_dsn()) as dsn:
        yield dsn


@pytest.fixture
def config(schema_dsn: str, tmp_path: Path) -> Config:
    source = tmp_path / "source"
    source.mkdir()
    data = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    data["paths"] = {"source_root": str(source), "results_root": str(tmp_path / "results")}
    data["db"] = {"dsn": schema_dsn}
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("truncate files, runs cascade")
    return Config.model_validate(data)


def _rows(dsn: str, sql: str = ROW) -> list[tuple]:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql).fetchall()


def _lock_free(dsn: str) -> bool:
    """Take and drop the run lock from another session: True if nobody held it."""
    with psycopg.connect(dsn, autocommit=True) as other:
        got = other.execute("select pg_try_advisory_lock(%s)", (RUN_LOCK_KEY,)).fetchone()[0]
        if got:
            other.execute("select pg_advisory_unlock(%s)", (RUN_LOCK_KEY,))
        return got


def _node(name: str, result: object) -> Node:
    return Node(name, lambda conn, ctx: result)


def _raising(name: str, error: BaseException) -> Node:
    def boom(conn: psycopg.Connection, ctx: NodeContext) -> object:
        raise error

    return Node(name, boom)


def test_a_run_ends_finished_with_its_counts(config: Config) -> None:
    sanitized = SanitizeResult(
        sanitized=2, errored=1, by_reason=MappingProxyType({"sanitize_name_failed": 1})
    )
    nodes = (_node("ingest", IngestResult(new=3, duplicate=1)), _node("sanitize", sanitized))

    result = run(config, dry_run=True, nodes=nodes)

    counts = {
        "ingest": {"new": 3, "skipped_known": 0, "skipped_unreadable": 0, "duplicate": 1},
        "sanitize": {"sanitized": 2, "errored": 1, "errored_name_failed": 1},
    }
    assert _rows(config.db.dsn) == [("dry_run", "finished", True, counts, None)]
    assert result.record_id == _rows(config.db.dsn, "select id from runs")[0][0]
    assert result.counts["sanitize"] is sanitized  # RunResult is unchanged for the CLI
    assert _lock_free(config.db.dsn)


def test_while_running_the_row_is_running_and_the_lock_is_held(config: Config) -> None:
    seen: list[object] = []

    def look(conn: psycopg.Connection, ctx: NodeContext) -> object:
        seen.append(_rows(ctx.config.db.dsn, "select state, counts, finished_at from runs"))
        seen.append(_lock_free(ctx.config.db.dsn))
        return None

    run(config, dry_run=True, nodes=(_node("ingest", 2), Node("sanitize", look)))

    # The earlier node's counts are already written (a bare number is {"count": n}).
    assert seen == [[("running", {"ingest": {"count": 2}}, None)], False]
    assert _rows(config.db.dsn, "select state, counts from runs") == [
        ("finished", {"ingest": {"count": 2}, "sanitize": {}})
    ]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (RuntimeError(f"{PLANT} at /source/{PLANT}.png"), "internal"),
        (KeyboardInterrupt(), "interrupted"),
        (psycopg.errors.UndefinedTable(f"{PLANT} table"), "database"),
    ],
)
def test_a_failing_node_marks_the_run_failed_and_frees_the_lock(
    config: Config, error: BaseException, code: str
) -> None:
    nodes = (_node("ingest", IngestResult(new=1)), _raising("sanitize", error))

    with pytest.raises(type(error)) as caught:
        run(config, dry_run=True, nodes=nodes)

    assert caught.value is error  # re-raised unchanged; the CLI's handling stays as it was
    ingest = {"new": 1, "skipped_known": 0, "skipped_unreadable": 0, "duplicate": 0}
    assert _rows(config.db.dsn) == [("dry_run", "failed", True, {"ingest": ingest}, code)]
    assert code in RUN_ERRORS
    assert _lock_free(config.db.dsn)


def test_a_held_lock_refuses_the_run_and_writes_nothing(config: Config) -> None:
    ran: list[str] = []

    def mark(conn: psycopg.Connection, ctx: NodeContext) -> object:
        ran.append("ingest")
        return None

    with psycopg.connect(config.db.dsn, autocommit=True) as holder:
        assert holder.execute("select pg_try_advisory_lock(%s)", (RUN_LOCK_KEY,)).fetchone()[0]
        with pytest.raises(RunLockedError) as caught:
            run(config, dry_run=True, nodes=(Node("ingest", mark),))
        holder.execute("select pg_advisory_unlock(%s)", (RUN_LOCK_KEY,))

    assert str(caught.value) == "another run holds the run lock; wait for it to finish"
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert ran == []
    assert _rows(config.db.dsn) == []
    assert _lock_free(config.db.dsn)


def test_runs_follow_each_other_once_the_lock_is_free(config: Config) -> None:
    first = run(config, dry_run=True, nodes=(_node("ingest", 1),))
    second = run(config, dry_run=True, nodes=(_node("ingest", 2),))
    assert first.record_id is not None and second.record_id is not None
    assert second.record_id > first.record_id
    assert _rows(config.db.dsn, "select state, counts from runs order by id") == [
        ("finished", {"ingest": {"count": 1}}),
        ("finished", {"ingest": {"count": 2}}),
    ]


def test_a_count_runs_counts_cannot_hold_fails_the_run_with_fixed_text(config: Config) -> None:
    from classifier.graph.run_record import CountsShapeError

    nodes = (_node("ingest", {f"/source/{PLANT}.png": 1}),)
    with pytest.raises(CountsShapeError) as caught:
        run(config, dry_run=True, nodes=nodes)

    assert PLANT not in str(caught.value)
    assert _rows(config.db.dsn, "select state, counts, error from runs") == [
        ("failed", {}, "internal")
    ]
    assert _lock_free(config.db.dsn)


def test_a_planted_name_is_held_in_the_ledger_and_absent_from_runs(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    folder = Path(config.paths.source_root) / f"{PLANT} trip"
    folder.mkdir()
    Image.new("RGB", (8, 6), (10, 20, 30)).save(folder / f"{PLANT}_one.png")

    with caplog.at_level(logging.DEBUG):
        run(config, dry_run=True, nodes=(INGEST,))

    # Proved held first: the ledger stores the source path (DOC-004.D3)...
    paths = _rows(config.db.dsn, "select source_path from files")
    assert len(paths) == 1 and PLANT in paths[0][0]
    # ...then absent from every column of runs, and from the log.
    whole = _rows(config.db.dsn, "select row_to_json(r)::text from runs r")
    assert len(whole) == 1 and '"state":"finished"' in whole[0][0]
    assert PLANT not in whole[0][0]
    assert PLANT not in caplog.text


# --- PIPE-002.2: orphaned running rows (PIPE-002.D3) ---------------------------------------

ORPHAN = (
    "insert into runs (kind, state, started_at, counts) "
    "values ('dry_run', 'running', now() - interval '1 hour', %s) returning id"
)


def _seed(dsn: str, sql: str, *params: object) -> int:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql, params).fetchone()[0]


def _by_id(dsn: str) -> dict[int, tuple]:
    rows = _rows(dsn, "select id, state, error, counts, finished_at >= started_at from runs")
    return {row[0]: row[1:] for row in rows}


def test_the_next_run_marks_an_orphan_interrupted(
    config: Config, caplog: pytest.LogCaptureFixture
) -> None:
    dsn = config.db.dsn
    first = _seed(dsn, ORPHAN, '{"ingest": {"new": 2}}')
    second = _seed(dsn, ORPHAN, "{}")

    with caplog.at_level(logging.INFO, logger="classifier.graph.run"):
        result = run(config, dry_run=True, nodes=(_node("ingest", 1),))

    rows = _by_id(dsn)
    assert rows[first] == ("failed", "interrupted", {"ingest": {"new": 2}}, True)  # counts kept
    assert rows[second] == ("failed", "interrupted", {}, True)
    assert rows[result.record_id] == ("finished", None, {"ingest": {"count": 1}}, True)
    swept = [r.getMessage() for r in caplog.records if "orphaned" in r.getMessage()]
    assert len(swept) == 1 and swept[0].endswith("marked 2 orphaned run(s) interrupted")


def test_finished_and_failed_rows_are_untouched(config: Config) -> None:
    dsn = config.db.dsn
    done = _seed(
        dsn,
        "insert into runs (kind, state, started_at, finished_at, counts) values "
        "('sort', 'finished', now() - interval '2 hours', now() - interval '1 hour', %s) "
        "returning id",
        '{"ingest": {"new": 5}}',
    )
    failed = _seed(
        dsn,
        "insert into runs (kind, state, started_at, finished_at, error) values "
        "('dry_run', 'failed', now() - interval '2 hours', now() - interval '1 hour', "
        "'database') returning id",
    )
    before = _rows(dsn, f"select * from runs where id in ({done}, {failed}) order by id")

    run(config, dry_run=True, nodes=(_node("ingest", 1),))

    assert _rows(dsn, f"select * from runs where id in ({done}, {failed}) order by id") == before


def test_with_the_lock_held_elsewhere_the_orphan_stays_running(config: Config) -> None:
    dsn = config.db.dsn
    orphan = _seed(dsn, ORPHAN, "{}")
    with psycopg.connect(dsn, autocommit=True) as holder:
        assert holder.execute("select pg_try_advisory_lock(%s)", (RUN_LOCK_KEY,)).fetchone()[0]
        with pytest.raises(RunLockedError):
            run(config, dry_run=True, nodes=(_node("ingest", 1),))
        holder.execute("select pg_advisory_unlock(%s)", (RUN_LOCK_KEY,))

    assert _rows(dsn, "select id, state, error, finished_at from runs") == [
        (orphan, "running", None, None)
    ]
