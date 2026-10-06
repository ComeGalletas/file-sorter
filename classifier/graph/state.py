"""The graph's state and the result of one run (PIPE-001.1, R-PIPE-1)."""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TypedDict

from classifier.graph.ingest import IngestResult


class GraphState(TypedDict):
    """What flows between nodes. `counts` holds each finished node's summary by node name."""

    run_id: str
    dry_run: bool
    counts: dict[str, object]


@dataclass(frozen=True)
class RunResult:
    """What one `run` did: the summary counts per node, in the order the nodes ran."""

    run_id: str
    dry_run: bool
    counts: "MappingProxyType[str, object]" = field(default_factory=lambda: MappingProxyType({}))

    @property
    def ingest(self) -> IngestResult:
        """The ingest node's counts (CLI-002 and gate 1 read these)."""
        found = self.counts["ingest"]
        assert isinstance(found, IngestResult)
        return found
