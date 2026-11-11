"""`run`: execute the nodes in order over the ledger (PIPE-001.1, R-PIPE-1, R-PIPE-2).

The graph is a LangGraph `StateGraph`, one node per pipeline stage. `run` commits once per
node (PIPE-001.D3), so a crash in node N+1 keeps node N's status checkpoint and a resumed
run selects by status (P-4). A node that raises rolls back its own work only, and the
exception propagates. A dry run skips `fileops` and ends at the last status a node set
(PIPE-001.D1); nothing sets `proposed` before `name` exists (M5).

PIPE-002.1: a run first takes the run lock (DB-007.D1) on its own record connection, which
lives as long as the run, then records itself in `runs`: `running`, its counts after each
node, then `finished`, or `failed` with a fixed code (DB-007.D3). The lock is released in a
`finally`. If another run holds it, `run` raises RunLockedError and writes nothing.
"""

import logging
import uuid
from collections.abc import Callable
from pathlib import Path
from types import MappingProxyType

import httpx
import psycopg
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import Connection, create_engine, func, insert, update
from sqlalchemy.pool import NullPool

from classifier.config import Config
from classifier.db.models import Run
from classifier.db.runlock import release_run_lock, try_run_lock
from classifier.db.url import to_sqlalchemy_url
from classifier.graph.nodes import REGISTRY, Node, NodeContext, plan
from classifier.graph.run_record import error_code, flatten
from classifier.graph.state import GraphState, RunResult
from classifier.models.vision import VisionBackend

log = logging.getLogger(__name__)

_RUNS = Run.__table__


class RunLockedError(Exception):
    """Another run holds the run lock (PIPE-002.D1). Fixed text."""

    def __init__(self) -> None:
        super().__init__("another run holds the run lock; wait for it to finish")


def run(
    config: Config,
    *,
    dry_run: bool = False,
    nodes: tuple[Node, ...] = REGISTRY,
    ollama_transport: httpx.BaseTransport | None = None,
    vision: VisionBackend | None = None,
) -> RunResult:
    """Run the pipeline once over `paths.source_root` and return the counts per node.

    `nodes` is for tests and later milestones; it defaults to the registered nodes.
    `ollama_transport` and `vision` are for tests only (TST-005.1's and TST-008.1's replay,
    or a failing fake); None means the real services.
    """
    dsn = config.db.dsn
    if not dsn:
        raise ValueError("config.db.dsn is not set: load the config with load_config")
    ctx = NodeContext(
        source_root=Path(config.paths.source_root),
        dry_run=dry_run,
        results_root=Path(config.paths.results_root),
        config=config,
        ollama_transport=ollama_transport,
        vision=vision,
    )
    steps = plan(nodes, dry_run)
    run_id = uuid.uuid4().hex

    engine = create_engine(to_sqlalchemy_url(dsn), poolclass=NullPool)
    try:
        with engine.connect() as record:
            locked = try_run_lock(record)
            record.commit()
            if not locked:
                raise RunLockedError()
            try:
                return _locked_run(record, steps, ctx, run_id, dry_run, dsn)
            finally:
                _release(record)
    finally:
        engine.dispose()


def _locked_run(
    record: Connection,
    steps: tuple[Node, ...],
    ctx: NodeContext,
    run_id: str,
    dry_run: bool,
    dsn: str,
) -> RunResult:
    kind = "dry_run" if dry_run else "sort"
    record_id = record.execute(insert(_RUNS).values(kind=kind).returning(_RUNS.c.id)).scalar_one()
    record.commit()
    log.info(
        "run %s (record %d): dry_run=%s nodes=%s",
        run_id[:8], record_id, dry_run, [n.name for n in steps],
    )  # fmt: skip
    counts: dict[str, dict[str, int | float]] = {}

    def recorded(name: str, result: object) -> None:
        counts[name] = flatten(name, result)
        record.execute(update(_RUNS).where(_RUNS.c.id == record_id).values(counts=dict(counts)))
        record.commit()

    try:
        with psycopg.connect(dsn) as conn:
            graph = _build(steps, conn, ctx, recorded)
            final = graph.invoke({"run_id": run_id, "dry_run": dry_run, "counts": {}})
    except BaseException as error:
        _fail(record, record_id, error_code(error))
        raise
    record.execute(
        update(_RUNS)
        .where(_RUNS.c.id == record_id)
        .values(state="finished", finished_at=func.clock_timestamp())
    )
    record.commit()
    return RunResult(run_id, dry_run, MappingProxyType(dict(final["counts"])), record_id)


def _fail(record: Connection, record_id: int, code: str) -> None:
    """Best effort: if the record connection is gone too, the row stays `running`."""
    try:
        record.rollback()
        record.execute(
            update(_RUNS)
            .where(_RUNS.c.id == record_id)
            .values(state="failed", finished_at=func.clock_timestamp(), error=code)
        )
        record.commit()
    except Exception:  # noqa: BLE001 — the run's own error is what propagates
        log.warning("run record %d: could not mark it failed (%s)", record_id, code)


def _release(record: Connection) -> None:
    try:
        release_run_lock(record)
        record.commit()
    except Exception:  # noqa: BLE001 — a dead session has dropped the lock already
        log.warning("run lock: release failed; the session's end drops it")


def _build(
    steps: tuple[Node, ...],
    conn: psycopg.Connection,
    ctx: NodeContext,
    recorded: Callable[[str, object], None],
) -> CompiledStateGraph:
    builder = StateGraph(GraphState)
    previous = START
    for node in steps:
        builder.add_node(node.name, _wrap(node, conn, ctx, recorded))
        builder.add_edge(previous, node.name)
        previous = node.name
    builder.add_edge(previous, END)
    return builder.compile()


def _wrap(
    node: Node,
    conn: psycopg.Connection,
    ctx: NodeContext,
    recorded: Callable[[str, object], None],
) -> Callable[[GraphState], dict[str, object]]:
    def step(state: GraphState) -> dict[str, object]:
        try:
            result = node.run(conn, ctx)
        except BaseException:
            conn.rollback()  # PIPE-001.D3: only this node's work is undone
            raise
        conn.commit()
        recorded(node.name, result)  # PIPE-002.1: the run's counts after each node
        return {"counts": {**state["counts"], node.name: result}}

    return step
