"""PIPE-001.1: the batch graph with the ingest node, in dry-run mode (the acceptance test).

Synthetic images only, generated here under `tmp_path`. The module runs against its own
migrated schema, because `run` commits (PIPE-001.D3).
"""

from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
import yaml
from PIL import Image

from classifier.config import Config
from classifier.graph.nodes import REGISTRY, Node, NodeContext, select_by_status
from classifier.graph.run import run
from tests.db.db_support import require_db_dsn
from tests.integration.schema_support import migrated_schema

REAL_CONFIG = Path(__file__).resolve().parents[2] / "config.yaml"


@pytest.fixture(scope="module")
def schema_dsn() -> Iterator[str]:
    with migrated_schema(require_db_dsn()) as dsn:
        yield dsn


@pytest.fixture(autouse=True)
def clean_ledger(schema_dsn: str) -> None:
    """Each test starts on an empty ledger of this module's own schema."""
    with psycopg.connect(schema_dsn) as conn:
        conn.execute("truncate files")


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    return root


def _config(source: Path, tmp_path: Path, dsn: str) -> Config:
    data = yaml.safe_load(REAL_CONFIG.read_text(encoding="utf-8"))
    data["paths"] = {"source_root": str(source), "results_root": str(tmp_path / "results")}
    data["db"] = {"dsn": dsn}
    return Config.model_validate(data)


def _png(path: Path, color: int) -> Path:
    Image.new("RGB", (8, 6), (color, 20, 30)).save(path)
    return path


def _populate(source: Path) -> None:
    """Two distinct images, a byte-identical copy of one, and a file that isn't an image."""
    first = _png(source / "a.png", 10)
    _png(source / "b.png", 200)
    (source / "copy.png").write_bytes(first.read_bytes())
    (source / "notes.txt").write_text("not an image")


def _rows(dsn: str, sql: str = "select source_hash, status from files order by 1") -> list:
    with psycopg.connect(dsn) as conn:
        return conn.execute(sql).fetchall()


def _statuses(dsn: str) -> list[str]:
    return sorted(status for _, status in _rows(dsn))


def _tree(root: Path) -> list[tuple[str, int]]:
    return sorted((str(p.relative_to(root)), p.stat().st_size) for p in root.rglob("*"))


class TestDryRun:
    def test_second_run_selects_nothing_new(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        config = _config(source, tmp_path, schema_dsn)

        first = run(config, dry_run=True)
        rows_after_first = _rows(schema_dsn)
        second = run(config, dry_run=True)

        assert first.dry_run and second.dry_run
        assert list(first.counts) == ["ingest"]  # M1: ingest is the only node, no fileops
        assert first.ingest.new == 2
        assert first.ingest.duplicate == 1
        assert first.ingest.skipped_unreadable == 1
        assert first.ingest.total == 4
        assert second.ingest.new == 0
        assert second.ingest.skipped_known == second.ingest.total == 4
        assert _rows(schema_dsn) == rows_after_first  # statuses and hashes unchanged
        assert len(rows_after_first) == 3

    def test_dry_run_ends_at_the_last_status_a_node_set(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        # PIPE-001.D1: no `proposed` until `name` exists.
        _populate(source)
        run(_config(source, tmp_path, schema_dsn), dry_run=True)
        assert set(_statuses(schema_dsn)) == {"queued", "skipped"}
        sql = "select count(*) from files where proposed_path is not null"
        assert _rows(schema_dsn, sql) == [(0,)]

    def test_nothing_is_written_under_the_source_or_results(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        before = _tree(source)
        run(_config(source, tmp_path, schema_dsn), dry_run=True)
        assert _tree(source) == before
        assert not (tmp_path / "results").exists()

    def test_run_ids_differ_per_run(self, source: Path, tmp_path: Path, schema_dsn: str) -> None:
        config = _config(source, tmp_path, schema_dsn)
        assert run(config, dry_run=True).run_id != run(config, dry_run=True).run_id


def _classify_stand_in(conn: psycopg.Connection, ctx: NodeContext) -> object:
    """Stands in for M2's node: it owns format, topic and nsfw_score and rewrites all three."""
    batch = select_by_status(conn, "queued")
    conn.execute(
        "update files set status = 'classified', format = 'new', topic = null, nsfw_score = 0.1"
        " where source_hash = any(%s)",
        (batch,),
    )
    return len(batch)


class TestErrorRetry:
    def test_a_retry_leaves_downstream_columns_for_their_owners_to_overwrite(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        # PIPE-001.D2: the graph clears nothing; each node overwrites its own columns.
        _png(source / "a.png", 10)
        config = _config(source, tmp_path, schema_dsn)
        run(config, dry_run=True)
        with psycopg.connect(schema_dsn) as conn:
            conn.execute(
                "update files set status = 'error', error = 'boom', nsfw_score = 0.9,"
                " format = 'old', topic = 'old', caption = '{\"old\": 1}', template = 'old',"
                " proposed_path = 'old', output_path = 'old', reference_id = 7"
            )

        retried = run(config, dry_run=True)
        assert retried.ingest.new == 1  # the retry counts as new
        sql = "select status, error, format from files"
        assert _rows(schema_dsn, sql) == [("queued", None, "old")]  # the graph cleared nothing

        result = run(config, dry_run=True, nodes=(*REGISTRY, Node("classify", _classify_stand_in)))
        assert result.counts["classify"] == 1
        sql = "select status, format, topic, nsfw_score from files"
        assert _rows(schema_dsn, sql) == [("classified", "new", None, 0.1)]  # its own, rewritten
        sql = "select caption, template, proposed_path, output_path, reference_id from files"
        assert _rows(schema_dsn, sql) == [({"old": 1}, "old", "old", "old", 7)]  # others untouched


class TestCommitPerNode:
    def test_a_later_node_that_raises_keeps_ingest_and_rolls_back_its_own_work(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        config = _config(source, tmp_path, schema_dsn)

        def explode(conn: psycopg.Connection, ctx: NodeContext) -> object:
            conn.execute("update files set status = 'sanitized'")
            raise RuntimeError("sanitize failed")

        with pytest.raises(RuntimeError, match="sanitize failed"):
            run(config, dry_run=True, nodes=(*REGISTRY, Node("sanitize", explode)))

        assert _statuses(schema_dsn) == ["queued", "queued", "skipped"]  # ingest kept, rest undone

    def test_a_resumed_run_selects_by_status_from_the_ledger(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        config = _config(source, tmp_path, schema_dsn)

        def crash(conn: psycopg.Connection, ctx: NodeContext) -> object:
            raise RuntimeError("crash")

        with pytest.raises(RuntimeError):
            run(config, dry_run=True, nodes=(*REGISTRY, Node("sanitize", crash)))

        def sanitize(conn: psycopg.Connection, ctx: NodeContext) -> object:
            batch = select_by_status(conn, "queued")
            conn.execute(
                "update files set status = 'sanitized' where source_hash = any(%s)", (batch,)
            )
            return len(batch)

        resumed = run(config, dry_run=True, nodes=(*REGISTRY, Node("sanitize", sanitize)))
        assert resumed.ingest.new == 0
        assert resumed.ingest.skipped_known == 4
        assert resumed.counts["sanitize"] == 2  # the two queued rows, found by status
        assert _statuses(schema_dsn) == ["sanitized", "sanitized", "skipped"]


class TestSelectByStatus:
    def test_selects_by_status_and_honours_the_limit(
        self, source: Path, tmp_path: Path, schema_dsn: str
    ) -> None:
        _populate(source)
        run(_config(source, tmp_path, schema_dsn), dry_run=True)
        with psycopg.connect(schema_dsn) as conn:
            queued = select_by_status(conn, "queued")
            assert len(queued) == 2
            assert select_by_status(conn, "queued", limit=1) == queued[:1]
            assert len(select_by_status(conn, "skipped")) == 1
            assert select_by_status(conn, "proposed") == []
