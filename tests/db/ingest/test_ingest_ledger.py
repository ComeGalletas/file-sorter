"""ING-001.2: the ingest node against the migrated test database (the acceptance test).

Synthetic images only, generated here under `tmp_path`. Rows are written through the shared
`db` fixture, so each test's rows are rolled back at teardown (TST-002.1).
"""

import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest
from PIL import Image

from classifier.graph import ingest as ingest_module
from classifier.graph.ingest import IngestResult, ingest
from classifier.graph.ingest_files import hash_file

OLD = datetime(2001, 1, 1, tzinfo=UTC)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    root = tmp_path / "source"
    root.mkdir()
    return root


def _png(path: Path, color: int = 0) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 6), (color, 20, 30)).save(path)
    return path


def _gif(path: Path) -> Path:
    first, second = (Image.new("RGB", (8, 6), (i * 90, 0, 0)) for i in range(2))
    first.save(path, save_all=True, append_images=[second], duration=50)
    return path


def _row(db: psycopg.Connection, path: Path) -> dict[str, object]:
    cur = db.execute("select * from files where source_hash = %s", (hash_file(path).source_hash,))
    names = [c.name for c in cur.description or []]
    found = cur.fetchone()
    assert found is not None, "no ledger row for this file"
    return dict(zip(names, found, strict=True))


def _count(db: psycopg.Connection) -> int:
    found = db.execute("select count(*) from files").fetchone()
    assert found is not None
    return int(found[0])


def _snapshot(db: psycopg.Connection) -> list[tuple[object, ...]]:
    return db.execute("select * from files order by source_hash").fetchall()


class TestNewFiles:
    def test_a_new_image_gets_a_queued_row(self, db: psycopg.Connection, source: Path) -> None:
        path = _png(source / "one.PNG")
        result = ingest(db, source)
        assert result == IngestResult(new=1)
        row = _row(db, path)
        digest = hash_file(path)
        assert row["short_hash"] == digest.short_hash
        assert (row["status"], row["ext"]) == ("queued", "png")
        assert (row["source_path"], row["duplicate_paths"]) == (str(path), [])
        assert (row["animated"], row["error"], row["needs_review"]) == (False, None, False)
        mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        assert row["source_mtime"] == mtime  # R-ING-4

    def test_animated_is_recorded(self, db: psycopg.Connection, source: Path) -> None:
        path = _gif(source / "moving.gif")
        ingest(db, source)
        assert _row(db, path)["animated"] is True

    def test_the_classification_columns_are_left_for_later_nodes(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        # files.format is the classification axis, not Pillow's format: ingest never fills it
        path = _png(source / "a.png")
        ingest(db, source)
        row = _row(db, path)
        assert all(row[name] is None for name in ("format", "topic", "branch", "nsfw_score"))

    def test_a_non_image_is_hashed_and_recorded_as_skipped(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        notes = source / "notes.txt"
        notes.write_text("synthetic")
        result = ingest(db, source)
        assert result == IngestResult(skipped_unreadable=1)
        row = _row(db, notes)
        assert (row["status"], row["error"], row["ext"]) == ("skipped", "not an image type", "txt")
        assert row["animated"] is None

    def test_an_undecodable_image_is_skipped_with_the_exception_type_as_reason(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        fake = source / "fake.png"
        fake.write_text("not an image")
        result = ingest(db, source)
        assert result == IngestResult(skipped_unreadable=1)
        row = _row(db, fake)
        assert row["status"] == "skipped"
        assert str(row["error"]).startswith("undecodable image (")
        assert "fake" not in str(row["error"])

    def test_os_metadata_files_leave_no_row(self, db: psycopg.Connection, source: Path) -> None:
        # R-ING-8
        for name in ("desktop.ini", "Thumbs.db", ".DS_Store"):
            (source / name).write_text("x")
        assert ingest(db, source) == IngestResult()
        assert _count(db) == 0

    def test_an_empty_folder_is_a_no_op(self, db: psycopg.Connection, source: Path) -> None:
        assert ingest(db, source) == IngestResult()
        assert _count(db) == 0


class TestKnownHashes:
    def test_a_rerun_writes_nothing_and_new_is_zero(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        # R-ING-2 and the M1 gate: re-running skips 100% of files with no new rows
        _png(source / "a.png", 1)
        _png(source / "sub" / "b.png", 2)
        _gif(source / "c.gif")
        (source / "notes.txt").write_text("synthetic")
        (source / "fake.png").write_text("not an image")
        first = ingest(db, source)
        assert first == IngestResult(new=3, skipped_unreadable=2)
        before = _snapshot(db)

        second = ingest(db, source)
        assert second == IngestResult(skipped_known=5)
        assert second.new == 0
        assert second.total == first.total == 5
        assert _snapshot(db) == before

    def test_a_known_row_is_not_touched(self, db: psycopg.Connection, source: Path) -> None:
        # updated_at is set by hand: now() is fixed inside a transaction, so only an
        # explicit old value shows whether the node wrote to the row
        path = _png(source / "a.png")
        ingest(db, source)
        db.execute("update files set updated_at = %s, status = 'filed'", (OLD,))
        ingest(db, source)
        row = _row(db, path)
        assert (row["updated_at"], row["status"]) == (OLD, "filed")

    @pytest.mark.parametrize("status", ["queued", "sanitized", "filed", "skipped", "deleted"])
    def test_any_status_but_error_is_known(
        self, db: psycopg.Connection, source: Path, status: str
    ) -> None:
        _png(source / "a.png")
        ingest(db, source)
        db.execute("update files set status = %s", (status,))
        assert ingest(db, source) == IngestResult(skipped_known=1)
        assert _snapshot(db)[0][_status_index(db)] == status

    def test_a_skipped_row_is_never_retried(self, db: psycopg.Connection, source: Path) -> None:
        # ING-001.D5: retries key on the status, and `skipped` is known even though its
        # reason sits in the `error` column
        fake = source / "fake.png"
        fake.write_text("not an image")
        ingest(db, source)
        db.execute("update files set updated_at = %s", (OLD,))
        assert ingest(db, source) == IngestResult(skipped_known=1)
        row = _row(db, fake)
        assert (row["status"], row["updated_at"]) == ("skipped", OLD)
        assert str(row["error"]).startswith("undecodable image")

    def test_an_error_row_is_retried(self, db: psycopg.Connection, source: Path) -> None:
        path = _png(source / "a.png")
        ingest(db, source)
        db.execute("update files set status = 'error', error = 'boom', updated_at = %s", (OLD,))
        assert ingest(db, source) == IngestResult(new=1)
        row = _row(db, path)
        assert (row["status"], row["error"]) == ("queued", None)
        assert row["updated_at"] != OLD
        assert _count(db) == 1

    def test_a_concurrent_insert_is_reported_as_known(
        self, db: psycopg.Connection, source: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The row appears between the status lookup and the insert: on conflict do nothing
        _png(source / "a.png")
        ingest(db, source)
        monkeypatch.setattr(ingest_module, "_status", lambda *_: None)
        assert ingest(db, source) == IngestResult(skipped_known=1)
        assert _count(db) == 1


def _status_index(db: psycopg.Connection) -> int:
    cur = db.execute("select * from files limit 0")
    return [c.name for c in cur.description or []].index("status")


class TestDuplicatePaths:
    def test_the_same_bytes_at_a_second_path_is_appended_not_reprocessed(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        first = _png(source / "a.png")
        second = source / "copy" / "a_again.png"
        second.parent.mkdir()
        second.write_bytes(first.read_bytes())
        result = ingest(db, source)
        assert result == IngestResult(new=1, duplicate=1)
        assert _count(db) == 1
        row = _row(db, first)
        # discover walks files before sub-folders, so the top-level copy is the first path
        assert (row["source_path"], row["duplicate_paths"]) == (str(first), [str(second)])

    def test_a_rerun_does_not_append_the_path_again(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        first = _png(source / "a.png")
        (source / "b.png").write_bytes(first.read_bytes())
        ingest(db, source)
        before = _snapshot(db)
        result = ingest(db, source)
        assert result == IngestResult(skipped_known=2)
        assert _snapshot(db) == before

    def test_three_copies_give_two_extra_paths_in_walk_order(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        first = _png(source / "a.png")
        for name in ("b.png", "c.png"):
            (source / name).write_bytes(first.read_bytes())
        assert ingest(db, source) == IngestResult(new=1, duplicate=2)
        row = _row(db, first)
        assert row["duplicate_paths"] == [str(source / "b.png"), str(source / "c.png")]

    def test_a_copy_found_on_a_later_run_is_appended_once(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        first = _png(source / "a.png")
        ingest(db, source)
        (source / "late.png").write_bytes(first.read_bytes())
        assert ingest(db, source) == IngestResult(skipped_known=1, duplicate=1)
        assert ingest(db, source) == IngestResult(skipped_known=2)
        assert _row(db, first)["duplicate_paths"] == [str(source / "late.png")]

    def test_a_duplicate_of_an_error_row_retries_it_instead(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        first = _png(source / "a.png")
        (source / "b.png").write_bytes(first.read_bytes())
        ingest(db, source)
        db.execute("update files set status = 'error', error = 'boom', duplicate_paths = '{}'")
        result = ingest(db, source)
        # a.png retries the row; b.png then finds it queued and is appended
        assert result == IngestResult(new=1, duplicate=1)
        assert _row(db, first)["status"] == "queued"

    def test_duplicate_non_images_are_recorded_once(
        self, db: psycopg.Connection, source: Path
    ) -> None:
        (source / "a.txt").write_text("same")
        (source / "b.txt").write_text("same")
        assert ingest(db, source) == IngestResult(skipped_unreadable=1, duplicate=1)
        assert _count(db) == 1


class TestUnhashableEntries:
    def test_a_symlink_gets_no_row_and_counts_every_run(
        self, db: psycopg.Connection, source: Path, tmp_path: Path
    ) -> None:
        # ING-001.D6
        outside = _png(tmp_path / "outside" / "target.png")
        (source / "link.png").symlink_to(outside)
        _png(source / "real.png", 5)
        first = ingest(db, source)
        second = ingest(db, source)
        assert first == IngestResult(new=1, skipped_unreadable=1)
        assert second == IngestResult(skipped_known=1, skipped_unreadable=1)
        assert _count(db) == 1  # the link's target was never hashed or recorded

    def test_an_unreadable_folder_gets_no_row_and_counts_every_run(
        self, db: psycopg.Connection, source: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # chmod can't hide a folder from root in the container, so its scan is made to fail
        _png(source / "ok.png")
        _png(source / "locked" / "hidden.png", 9)
        real_scandir = os.scandir
        target = str(source / "locked")

        def scandir(path: object = ".") -> object:
            if str(path) == target:
                raise PermissionError(13, "denied", target)
            return real_scandir(path)

        monkeypatch.setattr(os, "scandir", scandir)
        assert ingest(db, source) == IngestResult(new=1, skipped_unreadable=1)
        assert ingest(db, source) == IngestResult(skipped_known=1, skipped_unreadable=1)
        assert _count(db) == 1

    def test_a_file_that_vanishes_after_the_walk_is_skipped_unreadable(
        self, db: psycopg.Connection, source: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _png(source / "a.png")

        def gone(path: Path) -> object:
            raise FileNotFoundError(2, "gone")

        monkeypatch.setattr(ingest_module, "hash_file", gone)
        assert ingest(db, source) == IngestResult(skipped_unreadable=1)
        assert _count(db) == 0


class TestResultContract:
    def test_total_counts_every_walked_file_in_exactly_one_bucket(
        self, db: psycopg.Connection, source: Path, tmp_path: Path
    ) -> None:
        first = _png(source / "a.png")
        (source / "dup.png").write_bytes(first.read_bytes())
        (source / "notes.txt").write_text("synthetic")
        (source / "link.png").symlink_to(_png(tmp_path / "elsewhere.png", 7))
        (source / "desktop.ini").write_text("x")  # ignored: not walked
        result = ingest(db, source)
        assert result == IngestResult(new=1, duplicate=1, skipped_unreadable=2)
        assert result.total == 4

    def test_the_result_is_immutable(self) -> None:
        with pytest.raises(AttributeError):
            IngestResult().new = 1  # type: ignore[misc]


class TestSafety:
    def test_the_source_tree_is_never_modified(self, db: psycopg.Connection, source: Path) -> None:
        _png(source / "a.png")
        _gif(source / "b.gif")
        (source / "notes.txt").write_text("synthetic")
        (source / "fake.png").write_text("not an image")

        def tree() -> list[tuple[str, bytes, int]]:
            return [
                (p.relative_to(source).as_posix(), p.read_bytes(), p.stat().st_mtime_ns)
                for p in sorted(source.rglob("*"))
                if p.is_file()
            ]

        before = tree()
        ingest(db, source)
        ingest(db, source)
        assert tree() == before

    def test_logs_carry_hashes_and_never_a_path_or_name(
        self, db: psycopg.Connection, source: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        first = _png(source / "secret-name-xyz.png")
        (source / "secret-copy-xyz.png").write_bytes(first.read_bytes())
        (source / "secret-notes-xyz.txt").write_text("synthetic")
        with caplog.at_level(logging.DEBUG):
            ingest(db, source)
            ingest(db, source)
        text = caplog.text
        assert "ingest:" in text  # the node does log
        assert "secret" not in text
        assert str(source) not in text
        assert hash_file(first).short_hash in text  # a hash identifies the file
