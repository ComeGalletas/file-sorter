"""CLI-002.1.1: `RunResult.ingest` raises an explicit TypeError, which `python -O` can't strip."""

from types import MappingProxyType

import pytest

from classifier.graph.ingest import IngestResult
from classifier.graph.state import RunResult


def test_ingest_returns_the_ingest_result() -> None:
    found = IngestResult(new=2)
    result = RunResult("r", True, MappingProxyType({"ingest": found}))
    assert result.ingest is found


def test_ingest_rejects_a_foreign_count_with_type_error() -> None:
    result = RunResult("r", True, MappingProxyType({"ingest": 3}))
    with pytest.raises(TypeError, match="IngestResult"):
        _ = result.ingest
