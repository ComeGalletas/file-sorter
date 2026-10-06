"""PIPE-001.1: node order and the dry-run plan (R-PIPE-1, R-PIPE-2). No database."""

import pytest

from classifier.graph.nodes import PIPELINE_ORDER, REGISTRY, Node, plan


def _stub(name: str) -> Node:
    return Node(name, lambda conn, ctx: None)


def test_m1_registers_only_ingest() -> None:
    assert [n.name for n in REGISTRY] == ["ingest"]


def test_pipeline_order_is_the_design_order() -> None:
    assert PIPELINE_ORDER == (
        "ingest", "sanitize", "classify", "caption", "retrieve", "name", "fileops",
    )  # fmt: skip


def test_plan_sorts_nodes_into_pipeline_order() -> None:
    shuffled = tuple(_stub(n) for n in ("classify", "ingest", "sanitize"))
    assert [n.name for n in plan(shuffled, dry_run=False)] == ["ingest", "sanitize", "classify"]


def test_dry_run_drops_only_fileops() -> None:
    everything = tuple(_stub(n) for n in PIPELINE_ORDER)
    assert [n.name for n in plan(everything, dry_run=True)] == list(PIPELINE_ORDER[:-1])
    assert [n.name for n in plan(everything, dry_run=False)] == list(PIPELINE_ORDER)


def test_unknown_node_is_refused() -> None:
    with pytest.raises(ValueError, match="mystery"):
        plan((_stub("mystery"),), dry_run=False)
