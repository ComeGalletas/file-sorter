"""`run`: execute the nodes in order over the ledger (PIPE-001.1, R-PIPE-1, R-PIPE-2).

The graph is a LangGraph `StateGraph`, one node per pipeline stage. `run` commits once per
node (PIPE-001.D3), so a crash in node N+1 keeps node N's status checkpoint and a resumed
run selects by status (P-4). A node that raises rolls back its own work only, and the
exception propagates. A dry run skips `fileops` and ends at the last status a node set
(PIPE-001.D1); nothing sets `proposed` before `name` exists (M5).
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

from classifier.config import Config
from classifier.graph.nodes import REGISTRY, Node, NodeContext, plan
from classifier.graph.state import GraphState, RunResult

log = logging.getLogger(__name__)


def run(
    config: Config,
    *,
    dry_run: bool = False,
    nodes: tuple[Node, ...] = REGISTRY,
    ollama_transport: httpx.BaseTransport | None = None,
) -> RunResult:
    """Run the pipeline once over `paths.source_root` and return the counts per node.

    `nodes` is for tests and later milestones; it defaults to the registered nodes.
    `ollama_transport` is for tests only (TST-005.1's replay, or a failing fake).
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
    )
    steps = plan(nodes, dry_run)
    run_id = uuid.uuid4().hex
    log.info("run %s: dry_run=%s nodes=%s", run_id[:8], dry_run, [n.name for n in steps])

    with psycopg.connect(dsn) as conn:
        graph = _build(steps, conn, ctx)
        final = graph.invoke({"run_id": run_id, "dry_run": dry_run, "counts": {}})
    return RunResult(run_id, dry_run, MappingProxyType(dict(final["counts"])))


def _build(
    steps: tuple[Node, ...], conn: psycopg.Connection, ctx: NodeContext
) -> CompiledStateGraph:
    builder = StateGraph(GraphState)
    previous = START
    for node in steps:
        builder.add_node(node.name, _wrap(node, conn, ctx))
        builder.add_edge(previous, node.name)
        previous = node.name
    builder.add_edge(previous, END)
    return builder.compile()


def _wrap(
    node: Node, conn: psycopg.Connection, ctx: NodeContext
) -> Callable[[GraphState], dict[str, object]]:
    def step(state: GraphState) -> dict[str, object]:
        try:
            result = node.run(conn, ctx)
        except BaseException:
            conn.rollback()  # PIPE-001.D3: only this node's work is undone
            raise
        conn.commit()
        return {"counts": {**state["counts"], node.name: result}}

    return step
