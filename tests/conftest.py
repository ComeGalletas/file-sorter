"""Test tiers by path (CLAUDE.md §3, DOC-001.D8). Test modules stay plain pytest.

tests/unit/ -> unit, tests/db/ -> db, tests/integration/ -> integration, tests/gpu/ -> gpu.
A module anywhere else counts as `unit`. The tier audit (tests/devtools/test_tier_audit.py,
TST-002.2) fails any `unit` test that opens a db connection, loads a model or calls Ollama,
and names the move or the TIER_BY_DIR line below that fixes it.
"""

from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent
TIER_BY_DIR = {
    "unit": "unit",
    "db": "db",
    "integration": "integration",
    "gpu": "gpu",
    "gate": "gate",
}


def tier_of(path: Path) -> str:
    rel = path.resolve().relative_to(TESTS)
    return TIER_BY_DIR.get(rel.parts[0], "unit") if len(rel.parts) > 1 else "unit"


# tryfirst: the markers must exist before pytest's own `-m` deselection runs.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(getattr(pytest.mark, tier_of(Path(item.fspath))))
