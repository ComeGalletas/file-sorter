"""Test tiers by path (CLAUDE.md §3, DOC-001.D8). Test modules stay plain pytest.

tests/unit/ -> unit, tests/db/ -> db, tests/integration/ -> integration, tests/gpu/ -> gpu.
A module anywhere else counts as `unit`. The tier audit (tests/devtools/test_tier_audit.py,
TST-002.2) fails any `unit` test that opens a db connection, loads a model or calls Ollama,
and names the move or the TIER_BY_DIR line below that fixes it.

TST-005.1: the `ollama_transport` fixture gives a test the transport for `OllamaClient`.
Outside `gpu` it always replays recordings from tests/recordings/<package>/ and never reaches
Ollama. In `gpu` it is the real transport, or record mode with `pytest -m gpu --record-ollama`.
See tests/recordings/README.md.
"""

from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest

from tests.recordings.replay import RecordingTransport, ReplayTransport

TESTS = Path(__file__).resolve().parent
TIER_BY_DIR = {
    "unit": "unit",
    "db": "db",
    "integration": "integration",
    "gpu": "gpu",
    "gate": "gate",
}
RECORD_OPTION = "--record-ollama"
CALL_FAILED = pytest.StashKey[bool]()


def tier_of(path: Path) -> str:
    rel = path.resolve().relative_to(TESTS)
    return TIER_BY_DIR.get(rel.parts[0], "unit") if len(rel.parts) > 1 else "unit"


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        RECORD_OPTION,
        action="store_true",
        default=False,
        help="gpu tier only: write new Ollama recordings under tests/recordings/ (TST-005.1)",
    )


# tryfirst: the markers must exist before pytest's own `-m` deselection runs.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(getattr(pytest.mark, tier_of(Path(item.fspath))))


def pytest_collection_finish(session: pytest.Session) -> None:
    """Record mode runs only on a selection that is all `gpu` (after `-m` deselection)."""
    if not session.config.getoption(RECORD_OPTION):
        return
    others = [item.nodeid for item in session.items if tier_of(Path(item.fspath)) != "gpu"]
    if others:
        raise pytest.UsageError(
            f"{RECORD_OPTION} is for the gpu tier only, but the selection includes "
            f"{len(others)} other test(s), e.g. {others[0]}; run pytest -m gpu {RECORD_OPTION}"
        )


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    if report.when == "call":
        item.stash[CALL_FAILED] = report.failed
    return report


@pytest.fixture
def ollama_transport(
    request: pytest.FixtureRequest,
) -> Iterator[Callable[[str], httpx.BaseTransport]]:
    """A factory: `OllamaClient(host, transport=ollama_transport("models"))` (TST-005.1)."""
    gpu = tier_of(Path(request.node.fspath)) == "gpu"
    record = gpu and request.config.getoption(RECORD_OPTION)
    made: list[ReplayTransport | RecordingTransport] = []

    def make(package: str) -> httpx.BaseTransport:
        if not gpu:
            transport: ReplayTransport | RecordingTransport = ReplayTransport(
                package, request.node.nodeid
            )
        elif record:
            transport = RecordingTransport(package, httpx.HTTPTransport(), request.node.nodeid)
        else:
            return httpx.HTTPTransport()
        made.append(transport)
        return transport

    yield make
    # The second net: a recording failure the code under test caught still fails the test.
    # Skipped when the test already failed, so one miss is reported once.
    failures = [failure for transport in made for failure in transport.failures]
    if failures and not request.node.stash.get(CALL_FAILED, False):
        pytest.fail(
            f"Ollama recording failure caught by the code under test: {failures[0]}",
            pytrace=False,
        )
