"""Test tiers by path (CLAUDE.md §3, DOC-001.D8). Test modules stay plain pytest.

tests/unit/ -> unit, tests/db/ -> db, tests/integration/ -> integration, tests/gpu/ -> gpu.
A module anywhere else counts as `unit`. The tier audit (tests/devtools/test_tier_audit.py,
TST-002.2) fails any `unit` test that opens a db connection, loads a model or calls Ollama,
and names the move or the TIER_BY_DIR line below that fixes it.

TST-005.1: the `ollama_transport` fixture gives a test the transport for `OllamaClient`.
Outside `gpu` it always replays recordings from tests/recordings/<package>/ and never reaches
Ollama. In `gpu` it is the real transport, or record mode with `pytest -m gpu --record-ollama`.
See tests/recordings/README.md.

TST-008.1: the `vision_backend` fixture does the same for the `VisionBackend` seam (MOD-002.D1):
outside `gpu` it replays recordings, in `gpu` it is the real backend the test passes in, or
record mode with `pytest -m gpu --record-vision`.

TST-011.1: the `prompts_local_switch` fixture sets PROMPTS_LOCAL=off for every `unit`, `db` and
`integration` test, so the human's local prompt addenda (prompts/local/*.md, RUN-017) never reach
a default-tier run or its recordings (CLS-004.D16, TST-010). `off` means off; any other value
means on. The `gpu` and `gate` tiers get the variable cleared, so they use the addenda on the box.
A unit test of the addendum loader itself opts out with `@pytest.mark.prompts_local_on`; the
modules that do are pinned in tests/devtools/test_prompts_local_off.py.
It is set in os.environ, so a subprocess a test starts inherits it.
"""

from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.recordings.replay import (
    SERVED,
    RecordingTransport,
    ReplayTransport,
    orphan_recordings,
)
from tests.recordings.vision import register_test_model, unregister_test_model
from tests.recordings.vision_backend import (
    NO_UPSTREAM,
    RecordingVisionBackend,
    ReplayVisionBackend,
)

TESTS = Path(__file__).resolve().parent
TIER_BY_DIR = {
    "unit": "unit",
    "db": "db",
    "integration": "integration",
    "gpu": "gpu",
    "gate": "gate",
}
RECORD_OPTION = "--record-ollama"
RECORD_VISION_OPTION = "--record-vision"
RECORD_OPTIONS = (RECORD_OPTION, RECORD_VISION_OPTION)
CALL_FAILED = pytest.StashKey[bool]()
PROMPTS_LOCAL_ENV = "PROMPTS_LOCAL"
PROMPTS_LOCAL_MARK = "prompts_local_on"  # unit tests of the addendum loader itself
PROMPTS_LOCAL_TIERS = frozenset({"gpu", "gate"})  # the tiers that use the local addenda
DEFAULT_TIERS = ("unit", "db", "integration")  # what `make test` and the pre-push hook run


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
    parser.addoption(
        RECORD_VISION_OPTION,
        action="store_true",
        default=False,
        help="gpu tier only: write new vision recordings under tests/recordings/ (TST-008.1)",
    )


# tryfirst: the markers must exist before pytest's own `-m` deselection runs.
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    for item in items:
        item.add_marker(getattr(pytest.mark, tier_of(Path(item.fspath))))


def pytest_collection_finish(session: pytest.Session) -> None:
    """Record mode runs only on a selection that is all `gpu` (after `-m` deselection)."""
    chosen = [name for name in RECORD_OPTIONS if session.config.getoption(name)]
    if not chosen:
        return
    others = [item.nodeid for item in session.items if tier_of(Path(item.fspath)) != "gpu"]
    if others:
        raise pytest.UsageError(
            f"{chosen[0]} is for the gpu tier only, but the selection includes "
            f"{len(others)} other test(s), e.g. {others[0]}; run pytest -m gpu {chosen[0]}"
        )


def _addopts_markexpr(config: pytest.Config) -> str:
    """The `-m` expression of the ini `addopts`: what a run without its own `-m` selects."""
    words = list(config.getini("addopts"))
    return words[words.index("-m") + 1] if "-m" in words[:-1] else ""


def full_default_run(session: pytest.Session) -> bool:
    """True only for the whole default suite (TST-012.D2): the run that serves every recording.

    `make test` and the pre-push hook run bare `pytest`, which is that run. Anything that
    narrows it (a path, `-k`, `-m`, `--deselect`, `--ignore`, `-x`, `--lf`) or a tier that
    collected nothing makes it partial, so the orphan check does not run.
    """
    config, option = session.config, session.config.option
    if option.file_or_dir or option.keyword or option.collectonly:
        return False
    if option.markexpr != _addopts_markexpr(config):
        return False
    narrowing = ("deselect", "ignore", "ignore_glob", "lf", "failedfirst", "stepwise", "nf")
    if any(getattr(option, name, None) for name in narrowing) or option.maxfail:
        return False
    tiers = {tier_of(Path(item.fspath)) for item in session.items}
    return all(tier in tiers for tier in DEFAULT_TIERS)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail a full green default run when a committed recording was never served (TST-012.1.2).

    Prints the package and the first 8 hex of each key, nothing else. Never skipped: a
    partial run does not run it, a full run always does.
    """
    if exitstatus != pytest.ExitCode.OK or not full_default_run(session):
        return
    orphans = orphan_recordings(SERVED)
    if not orphans:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    line = "Orphaned recordings: " + " ".join(orphans)
    if reporter is not None:
        reporter.write_line(line, red=True)
    else:
        print(line)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]):
    report = yield
    if report.when == "call":
        item.stash[CALL_FAILED] = report.failed
    return report


@pytest.fixture(autouse=True)
def prompts_local_switch(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """PROMPTS_LOCAL=off outside `gpu` and `gate`; cleared inside them (TST-011.1)."""
    tier = tier_of(Path(request.node.fspath))
    if tier in PROMPTS_LOCAL_TIERS or (
        tier == "unit" and request.node.get_closest_marker(PROMPTS_LOCAL_MARK)
    ):
        monkeypatch.delenv(PROMPTS_LOCAL_ENV, raising=False)
    else:
        monkeypatch.setenv(PROMPTS_LOCAL_ENV, "off")


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


@pytest.fixture
def vision_backend(
    request: pytest.FixtureRequest,
) -> Iterator[Callable[..., Any]]:
    """A factory: `vision_backend("models", classifier_id, nsfw_id, upstream=None)` (TST-008.1).

    Outside `gpu` it replays. In `gpu` the test passes the real backend as `upstream`, which is
    returned as it is, or wrapped by the recorder under `--record-vision`.
    """
    gpu = tier_of(Path(request.node.fspath)) == "gpu"
    record = gpu and request.config.getoption(RECORD_VISION_OPTION)
    made: list[ReplayVisionBackend | RecordingVisionBackend] = []

    def make(package: str, classifier_id: str = "", nsfw_id: str = "", upstream: Any = None) -> Any:
        if not gpu:
            backend: ReplayVisionBackend | RecordingVisionBackend = ReplayVisionBackend(
                package, request.node.nodeid, classifier_id, nsfw_id
            )
        elif upstream is None:
            pytest.fail(NO_UPSTREAM, pytrace=False)
        elif record:
            backend = RecordingVisionBackend(package, upstream, request.node.nodeid)
        else:
            return upstream
        made.append(backend)
        return backend

    yield make
    failures = [failure for backend in made for failure in backend.failures]
    if failures and not request.node.stash.get(CALL_FAILED, False):
        pytest.fail(
            f"Vision recording failure caught by the code under test: {failures[0]}",
            pytrace=False,
        )


@pytest.fixture
def extra_vision_models() -> Iterator[Callable[..., None]]:
    """Register synthetic model ids for one test (TST-008.D9). Removed at teardown.

    The recordings lint accepts only the vision models in config.yaml; a test that records or
    replays with a made-up `owner/name` id registers it here, for its own run only.
    """
    added: list[str] = []

    def add(*models: str) -> None:
        for model in models:
            register_test_model(model)
            added.append(model)

    yield add
    for model in added:
        unregister_test_model(model)
