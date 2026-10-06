"""The node registry, in pipeline order, and the status-driven selector (R-PIPE-1, P-4).

Nodes are batch-oriented: each selects its files by ledger `status` and never reads a
downstream column before its owner rewrote it (PIPE-001.D2). A node never commits; `run`
commits once per node (PIPE-001.D3).
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import psycopg

from classifier.graph.ingest import ingest

# DESIGN.md §3 / C-7: the order later milestones fill in. Only `ingest` exists in M1.
PIPELINE_ORDER = ("ingest", "sanitize", "classify", "caption", "retrieve", "name", "fileops")
FILEOPS = "fileops"  # the one node a dry run skips (R-PIPE-2)


@dataclass(frozen=True)
class NodeContext:
    """What a node gets besides the connection: the folder to ingest and the run's mode."""

    source_root: Path
    dry_run: bool


@dataclass(frozen=True)
class Node:
    name: str
    run: Callable[[psycopg.Connection, NodeContext], object]


def _ingest(conn: psycopg.Connection, ctx: NodeContext) -> object:
    return ingest(conn, ctx.source_root)


REGISTRY: tuple[Node, ...] = (Node("ingest", _ingest),)


def plan(nodes: tuple[Node, ...], dry_run: bool) -> tuple[Node, ...]:
    """The nodes to run, in pipeline order; a dry run drops `fileops` (R-PIPE-2)."""
    order = {name: i for i, name in enumerate(PIPELINE_ORDER)}
    unknown = [n.name for n in nodes if n.name not in order]
    if unknown:
        raise ValueError(f"unknown node(s) {unknown}: add them to PIPELINE_ORDER (DESIGN.md §3)")
    ordered = sorted(nodes, key=lambda n: order[n.name])
    return tuple(n for n in ordered if not (dry_run and n.name == FILEOPS))


def select_by_status(conn: psycopg.Connection, status: str, limit: int | None = None) -> list[str]:
    """The source hashes of the rows at `status`, oldest first: a node's batch (P-4)."""
    sql = "select source_hash from files where status = %s order by created_at, source_hash"
    params: tuple[object, ...] = (status,)
    if limit is not None:
        sql += " limit %s"
        params += (limit,)
    return [str(row[0]) for row in conn.execute(sql, params).fetchall()]
