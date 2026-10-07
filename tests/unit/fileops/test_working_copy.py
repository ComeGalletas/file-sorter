"""FOP-001.1: the working copy in `.work/`. Synthetic bytes only, generated here."""

import errno
import hashlib
import os
import stat
from pathlib import Path

import pytest

from classifier.fileops.copy_move import WorkingCopy, make_working_copy, write_new

SOURCE_BYTES = b"synthetic-source-bytes" * 100
HASH = hashlib.sha256(SOURCE_BYTES).hexdigest()


def _append_marker(path: Path) -> None:
    with path.open("ab") as handle:
        handle.write(b"-stripped")


def _no_op(path: Path) -> None:
    return None


class TransformFailed(Exception):
    pass


def _fail_after_writing(path: Path) -> None:
    _append_marker(path)
    raise TransformFailed


@pytest.fixture
def source(tmp_path: Path) -> Path:
    folder = tmp_path / "source"
    folder.mkdir()
    path = folder / "a.bin"
    path.write_bytes(SOURCE_BYTES)
    return path


@pytest.fixture
def work_dir(tmp_path: Path) -> Path:
    return tmp_path / "results" / ".work"


@pytest.fixture(autouse=True)
def _results_root(tmp_path: Path) -> None:
    (tmp_path / "results").mkdir()


class TestMakeWorkingCopy:
    def test_publishes_the_transformed_copy_under_the_hash_name(
        self, source: Path, work_dir: Path
    ) -> None:
        result = make_working_copy(source, work_dir, HASH, "jpg", _append_marker)
        expected = SOURCE_BYTES + b"-stripped"
        assert result == WorkingCopy(work_dir / f"{HASH}.jpg", hashlib.sha256(expected).hexdigest())
        assert result.path.read_bytes() == expected
        assert sorted(p.name for p in work_dir.iterdir()) == [f"{HASH}.jpg"]

    def test_copy_sha256_is_of_the_copy_not_the_source(self, source: Path, work_dir: Path) -> None:
        result = make_working_copy(source, work_dir, HASH, "jpg", _append_marker)
        assert result.copy_sha256 != HASH
        assert result.copy_sha256 == hashlib.sha256(result.path.read_bytes()).hexdigest()

    def test_identity_transform_keeps_the_bytes(self, source: Path, work_dir: Path) -> None:
        result = make_working_copy(source, work_dir, HASH, "png", _no_op)
        assert result.path.read_bytes() == SOURCE_BYTES
        assert result.copy_sha256 == HASH

    def test_transform_runs_on_the_temp_file_before_the_rename(
        self, source: Path, work_dir: Path
    ) -> None:
        seen: list[tuple[str, bool]] = []

        def spy(path: Path) -> None:
            seen.append((path.name, (work_dir / f"{HASH}.jpg").exists()))

        make_working_copy(source, work_dir, HASH, "jpg", spy)
        assert seen == [(f".{HASH}.jpg.tmp", False)]  # FOP-001.D1

    def test_source_is_left_untouched(self, source: Path, work_dir: Path) -> None:
        before = source.stat()
        make_working_copy(source, work_dir, HASH, "jpg", _append_marker)
        after = source.stat()
        assert source.read_bytes() == SOURCE_BYTES
        assert (after.st_mtime_ns, after.st_size, after.st_mode) == (
            before.st_mtime_ns,
            before.st_size,
            before.st_mode,
        )
        assert sorted(p.name for p in source.parent.iterdir()) == [source.name]

    def test_read_only_source_is_enough(self, source: Path, work_dir: Path) -> None:
        source.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        try:
            result = make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        finally:
            source.chmod(stat.S_IRUSR | stat.S_IWUSR)
        assert result.path.read_bytes() == SOURCE_BYTES

    def test_failing_transform_leaves_no_file_and_reraises(
        self, source: Path, work_dir: Path
    ) -> None:
        with pytest.raises(TransformFailed):
            make_working_copy(source, work_dir, HASH, "jpg", _fail_after_writing)
        assert list(work_dir.iterdir()) == []
        assert source.read_bytes() == SOURCE_BYTES

    def test_missing_source_leaves_no_temp(self, tmp_path: Path, work_dir: Path) -> None:
        with pytest.raises(FileNotFoundError):
            make_working_copy(tmp_path / "missing.bin", work_dir, HASH, "jpg", _no_op)
        assert list(work_dir.iterdir()) == []

    def test_stale_temp_from_a_crashed_run_is_replaced(self, source: Path, work_dir: Path) -> None:
        work_dir.mkdir()
        (work_dir / f".{HASH}.jpg.tmp").write_bytes(b"half-written")
        result = make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert result.path.read_bytes() == SOURCE_BYTES
        assert sorted(p.name for p in work_dir.iterdir()) == [f"{HASH}.jpg"]

    def test_stale_working_copy_of_a_queued_row_is_replaced(
        self, source: Path, work_dir: Path
    ) -> None:
        work_dir.mkdir()
        (work_dir / f"{HASH}.jpg").write_bytes(b"stale-copy")  # R-FOP-6, FOP-001.D1
        result = make_working_copy(source, work_dir, HASH, "jpg", _append_marker)
        assert result.path.read_bytes() == SOURCE_BYTES + b"-stripped"

    def test_other_files_in_work_dir_are_left_alone(self, source: Path, work_dir: Path) -> None:
        work_dir.mkdir()
        other = work_dir / f"{'0' * 64}.jpg"
        other.write_bytes(b"other-copy")
        make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert other.read_bytes() == b"other-copy"

    @pytest.mark.parametrize(
        "bad_hash",
        ["", HASH[:8], HASH.upper(), HASH + "0", "../" + HASH[3:], "g" * 64],
    )
    def test_bad_source_hash_is_refused_before_writing(
        self, source: Path, work_dir: Path, bad_hash: str
    ) -> None:
        with pytest.raises(ValueError, match="source_hash"):
            make_working_copy(source, work_dir, bad_hash, "jpg", _no_op)
        assert not work_dir.exists()

    @pytest.mark.parametrize("bad_ext", ["", ".jpg", "jp/g", "jp\\g", "..", "a.b", "x" * 17])
    def test_bad_ext_is_refused_before_writing(
        self, source: Path, work_dir: Path, bad_ext: str
    ) -> None:
        with pytest.raises(ValueError, match="ext"):
            make_working_copy(source, work_dir, HASH, bad_ext, _no_op)
        assert not work_dir.exists()

    def test_rename_failure_removes_the_temp(
        self, source: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_replace(src: object, dst: object) -> None:
            raise OSError("simulated")

        monkeypatch.setattr(os, "replace", failing_replace)
        with pytest.raises(OSError, match="simulated"):
            make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert list(work_dir.iterdir()) == []


@pytest.fixture
def dest(work_dir: Path) -> Path:
    work_dir.mkdir()
    return work_dir / "thumbs" / f"{HASH}.webp"


def _names(folder: Path) -> list[str]:
    return sorted(p.name for p in folder.iterdir())


def _link_unsupported(code: int) -> object:
    def link(src: object, dst: object) -> None:
        raise OSError(code, "simulated: no hard links")

    return link


class TestWriteNew:
    def test_writes_when_absent_and_creates_the_folder(self, dest: Path) -> None:
        assert write_new(dest, b"thumb-bytes") is True
        assert dest.read_bytes() == b"thumb-bytes"
        assert _names(dest.parent) == [dest.name]

    def test_keeps_an_existing_file(self, dest: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        dest.parent.mkdir()
        dest.write_bytes(b"made-by-someone-else")
        before = dest.stat().st_mtime_ns
        monkeypatch.setattr(os, "link", _link_unsupported(errno.EIO))  # must not get this far
        assert write_new(dest, b"thumb-bytes") is False  # ING-002.D2
        assert dest.read_bytes() == b"made-by-someone-else"
        assert dest.stat().st_mtime_ns == before
        assert _names(dest.parent) == [dest.name]

    def test_file_appearing_before_the_link_is_kept(
        self, dest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_link = os.link

        def racing_link(src: Path, dst: Path) -> None:
            Path(dst).write_bytes(b"other-writer")
            real_link(src, dst)

        monkeypatch.setattr(os, "link", racing_link)
        assert write_new(dest, b"thumb-bytes") is False
        assert dest.read_bytes() == b"other-writer"
        assert _names(dest.parent) == [dest.name]

    def test_stale_temp_from_a_crashed_run_is_replaced(self, dest: Path) -> None:
        dest.parent.mkdir()
        (dest.parent / f".{dest.name}.tmp").write_bytes(b"half-written")
        assert write_new(dest, b"thumb-bytes") is True
        assert dest.read_bytes() == b"thumb-bytes"
        assert _names(dest.parent) == [dest.name]

    @pytest.mark.parametrize("code", [errno.EPERM, errno.ENOTSUP, errno.EOPNOTSUPP, errno.EXDEV])
    def test_fallback_writes_when_hard_links_are_unsupported(
        self, dest: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        monkeypatch.setattr(os, "link", _link_unsupported(code))  # FOP-001.D2
        assert write_new(dest, b"thumb-bytes") is True
        assert dest.read_bytes() == b"thumb-bytes"
        assert _names(dest.parent) == [dest.name]

    def test_fallback_keeps_a_file_that_appeared_meanwhile(
        self, dest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def appearing_then_unsupported(src: object, dst: Path) -> None:
            Path(dst).write_bytes(b"other-writer")
            raise OSError(errno.ENOTSUP, "simulated: no hard links")

        monkeypatch.setattr(os, "link", appearing_then_unsupported)  # FOP-001.D2
        assert write_new(dest, b"thumb-bytes") is False
        assert dest.read_bytes() == b"other-writer"
        assert _names(dest.parent) == [dest.name]

    def test_other_link_errors_propagate_and_leave_nothing(
        self, dest: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(os, "link", _link_unsupported(errno.EIO))
        with pytest.raises(OSError) as raised:
            write_new(dest, b"thumb-bytes")
        assert raised.value.errno == errno.EIO
        assert _names(dest.parent) == []
