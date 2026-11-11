"""TST-015.1.3: gate 4's runner over a migrated test schema, through `create_app` in-process.

Rows are synthetic and committed through their own connection (the app reads on its own
read-only engine), then deleted by hash. The routes that haven't landed yet (`/ui/review`,
`/`, SSE, the report) must fail as `NOT_AVAILABLE`, never pass. Plants are proved held (read
into the ledger) and served (no `NOT_SERVED`) before their absence is asserted.
"""

import hashlib
import importlib.util
import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from classifier.api.app import read_only_engine
from classifier.api.views import ADULT_BRANCH, PER_PAGE

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_4.py"
_spec = importlib.util.spec_from_file_location("gate_4_runner", SCRIPT)
assert _spec is not None and _spec.loader is not None
gate_4 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gate_4)

Code = gate_4.Code
BASE = datetime(2026, 11, 11, 3, 0, tzinfo=UTC)
PLANT_DIR = "Qorvex-Runner-Plant"
PLANT_STEM = "Zhyndel-Raw-Runner"
PLANT_DUP_STEM = "Vruthmar-Dup-Runner"
NOT_AVAILABLE = (("-", Code.NOT_AVAILABLE),)

Seed = Callable[..., str]


@pytest.fixture
def seed(migrated_db: str) -> Iterator[Seed]:
    hashes: list[str] = []
    conn = psycopg.connect(migrated_db, autocommit=True)

    def add(**cols: Any) -> str:
        source_hash = hashlib.sha256(uuid.uuid4().bytes).hexdigest()
        row: dict[str, Any] = {
            "source_hash": source_hash,
            "short_hash": source_hash[:8],
            # Not derived from the hash, which is served on purpose: the stem would match it.
            "source_path": f"/source/qorvex/raw-{uuid.uuid4().hex[:12]}.png",
            "source_mtime": BASE,
            "ext": "png",
            "status": "classified",
            "branch": "safe",
            "format": "qorvex-format",
            "topic": "zhyndel-topic",
            "original_sanitized": f"clean-{source_hash[:6]}",
            "updated_at": BASE,
        }
        row.update(cols)
        names = ", ".join(row)
        marks = ", ".join(f"%({k})s" for k in row)
        hashes.append(source_hash)
        conn.execute(f"insert into files ({names}) values ({marks})", row)
        return source_hash

    try:
        yield add
    finally:
        try:
            if hashes:
                conn.execute("delete from files where source_hash = any(%s)", [hashes])
        finally:
            conn.close()


def _ledger(migrated_db: str) -> list[Any]:
    engine = read_only_engine(migrated_db)
    try:
        return gate_4.read_ledger(engine)
    finally:
        engine.dispose()


def _seed_folder(seed: Seed) -> tuple[list[str], str]:
    """More than one page of rows, an adult row, a review row, an unsorted row and a plant."""
    hashes = [seed() for _ in range(PER_PAGE + 3)]
    hashes.append(seed(branch=ADULT_BRANCH))
    hashes.append(seed(needs_review=True, review_reason="nsfw_disagreement"))
    hashes.append(seed(format="unsorted", topic=None, status="classified"))
    hashes.append(seed(status="error", error="qorvex_error", format=None, topic=None))
    planted = seed(
        source_path=f"/source/{PLANT_DIR}/{PLANT_STEM}.png",
        duplicate_paths=[f"/source/{PLANT_DIR}/{PLANT_DUP_STEM}.png"],
        original_sanitized="qorvex-clean",
    )
    hashes.append(planted)
    return hashes, planted


def test_the_runner_reads_the_whole_ledger_and_holds_the_plants(migrated_db, seed) -> None:
    hashes, planted = _seed_folder(seed)
    ledger = _ledger(migrated_db)
    assert {r.source_hash for r in ledger} == set(hashes)  # this test's rows, and only them
    [row] = [r for r in ledger if r.source_hash == planted]
    assert row.source_path == f"/source/{PLANT_DIR}/{PLANT_STEM}.png"
    assert row.duplicate_paths == (f"/source/{PLANT_DIR}/{PLANT_DUP_STEM}.png",)
    assert gate_4.raw_stems(row) == [PLANT_STEM, PLANT_DUP_STEM]
    assert PLANT_DIR not in repr(row)


def test_the_runner_serves_every_row_and_never_a_path(migrated_db, seed) -> None:
    hashes, planted = _seed_folder(seed)
    findings = {f.criterion: f for f in gate_4.run(migrated_db, read_only_engine(migrated_db))}
    assert findings[1].passed, findings[1].issues  # paged past PER_PAGE to the empty page
    assert findings[2].passed, findings[2].issues  # counts and the grid, adult flag included
    assert findings[7].passed, findings[7].issues
    # Every row was served (no NOT_SERVED), the plant included, so the absence of LEAK_* means
    # something; the only issue is the sources that haven't landed yet (SSE, the UI, the report).
    assert findings[4].issues == NOT_AVAILABLE
    # Not landed yet: they fail, never pass (TST-015.1.4 wires them).
    for criterion in (3, 5, 6):
        assert findings[criterion].issues == NOT_AVAILABLE, criterion


def test_the_runner_fails_on_an_empty_ledger(migrated_db) -> None:
    assert _ledger(migrated_db) == []
    findings = {f.criterion: f for f in gate_4.run(migrated_db, read_only_engine(migrated_db))}
    for criterion in (1, 3, 4, 5):
        assert findings[criterion].issues == NOT_AVAILABLE, criterion


def test_main_detail_prints_hashes_and_codes_only(
    migrated_db, seed, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _seed_folder(seed)
    assert any(r.source_path.startswith(f"/source/{PLANT_DIR}/") for r in _ledger(migrated_db))
    monkeypatch.setenv("APP_DB_DSN", migrated_db)
    assert gate_4.main(["--detail"], engine=read_only_engine(migrated_db)) == 1  # not all landed
    out = capsys.readouterr()
    lines = out.out.splitlines()
    assert "gate 4 FAIL" in lines
    assert "gate 4 criterion 1 (every row reachable through /api/files): ok" in lines
    assert "  3 - NOT_AVAILABLE" in lines
    secrets = (PLANT_DIR, PLANT_STEM, PLANT_DUP_STEM, "qorvex-clean", "qorvex-format", "/source")
    for secret in secrets:
        assert secret not in out.out and secret not in out.err
    assert "postgresql" not in out.out and "postgresql" not in out.err
