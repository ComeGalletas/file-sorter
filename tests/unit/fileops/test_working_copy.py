"""FOP-001.1: the working copy in `.work/`. Synthetic bytes only, generated here."""

import errno
import hashlib
import os
import stat
from pathlib import Path

import pytest

from classifier.fileops.copy_move import (
    SOURCE_REFUSED,
    TEMP_FAILED,
    SourceRefusedError,
    WorkingCopy,
    make_working_copy,
    write_new,
)

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
        with pytest.raises(SourceRefusedError):
            make_working_copy(tmp_path / "missing.bin", work_dir, HASH, "jpg", _no_op)
        assert list(work_dir.iterdir()) == []

    def _refused(self, source: Path, work_dir: Path) -> SourceRefusedError:
        # SAN-003.1.2: raised from fixed text, unchained, nothing written
        with pytest.raises(SourceRefusedError) as raised:
            make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert str(raised.value) == SOURCE_REFUSED
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        assert list(work_dir.iterdir()) == []
        return raised.value

    @pytest.mark.parametrize("dangling", [False, True])
    def test_a_symlinked_original_is_refused_with_no_read(
        self, tmp_path: Path, work_dir: Path, dangling: bool
    ) -> None:
        target = tmp_path / "qorvex-target.bin"
        if not dangling:
            target.write_bytes(b"qorvex-secret-bytes")
        link = tmp_path / "zhyndel-link.bin"
        link.symlink_to(target)
        error = self._refused(link, work_dir)
        assert "qorvex" not in repr(error) and "zhyndel" not in repr(error)
        if not dangling:
            assert target.read_bytes() == b"qorvex-secret-bytes"

    def test_a_folder_is_refused(self, tmp_path: Path, work_dir: Path) -> None:
        folder = tmp_path / "qorvex-folder"
        folder.mkdir()
        self._refused(folder, work_dir)

    def test_a_fifo_is_refused_without_blocking(self, tmp_path: Path, work_dir: Path) -> None:
        fifo = tmp_path / "qorvex.fifo"
        os.mkfifo(fifo)
        self._refused(fifo, work_dir)

    def test_a_lone_surrogate_path_is_refused_with_fixed_text(
        self, tmp_path: Path, work_dir: Path
    ) -> None:
        error = self._refused(tmp_path / f"zhyndel-{chr(0xD800)}.bin", work_dir)
        assert "ud800" not in repr(error).lower()

    def test_a_nul_in_the_path_is_refused_with_fixed_text(
        self, tmp_path: Path, work_dir: Path
    ) -> None:
        self._refused(tmp_path / f"zhyndel{chr(0)}.bin", work_dir)

    def test_fstat_failure_closes_the_fd(
        self, source: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[int] = []
        real_open = os.open

        def spy_open(*args: object, **kwargs: object) -> int:
            fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
            opened.append(fd)
            return fd

        def failing_fstat(fd: int) -> object:
            raise OSError(5, "qorvex-planted-path")

        monkeypatch.setattr(os, "open", spy_open)
        monkeypatch.setattr(os, "fstat", failing_fstat)
        self._refused(source, work_dir)
        monkeypatch.undo()
        with pytest.raises(OSError) as closed:
            os.fstat(opened[0])
        assert closed.value.errno == errno.EBADF

    def test_stale_temp_from_a_crashed_run_is_replaced(self, source: Path, work_dir: Path) -> None:
        work_dir.mkdir()
        (work_dir / f".{HASH}.jpg.tmp").write_bytes(b"half-written")
        result = make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert result.path.read_bytes() == SOURCE_BYTES
        assert sorted(p.name for p in work_dir.iterdir()) == [f"{HASH}.jpg"]

    @pytest.mark.parametrize("dangling", [False, True])
    def test_a_symlink_at_the_temp_name_is_never_written_through(
        self, source: Path, work_dir: Path, tmp_path: Path, dangling: bool
    ) -> None:
        # SAN-001.D16 / SAN-001.4.2: a planted link can't redirect the copy.
        victim = tmp_path / "victim.bin"
        if not dangling:
            victim.write_bytes(b"victim")
        work_dir.mkdir()
        (work_dir / f".{HASH}.jpg.tmp").symlink_to(victim)
        result = make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert result.path.read_bytes() == SOURCE_BYTES
        assert not result.path.is_symlink()
        assert _names(work_dir) == [f"{HASH}.jpg"]
        if dangling:
            assert not victim.exists()
        else:
            assert victim.read_bytes() == b"victim"

    def test_a_link_planted_after_the_cleanup_is_refused(
        self, source: Path, work_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        victim = tmp_path / "victim.bin"
        victim.write_bytes(b"victim")
        real_open = os.open

        def racing_open(path: object, flags: int, mode: int = 0o777) -> int:
            if str(path).endswith(".tmp"):  # only the temp open races; the source open is real
                Path(str(path)).symlink_to(victim)
            return real_open(path, flags, mode)

        monkeypatch.setattr(os, "open", racing_open)
        with pytest.raises(OSError) as raised:  # EEXIST from O_EXCL, surfaced as fixed text
            make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert str(raised.value) == TEMP_FAILED
        assert raised.value.__cause__ is None and raised.value.__context__ is None
        assert victim.read_bytes() == b"victim"
        assert _names(work_dir) == []

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

    @pytest.mark.parametrize("dangling", [False, True])
    def test_a_symlink_at_the_temp_name_is_never_written_through(
        self, dest: Path, tmp_path: Path, dangling: bool
    ) -> None:
        # SAN-001.D16 / SAN-001.4.2: a planted link can't redirect the thumbnail.
        victim = tmp_path / "victim.bin"
        if not dangling:
            victim.write_bytes(b"victim")
        dest.parent.mkdir()
        (dest.parent / f".{dest.name}.tmp").symlink_to(victim)
        assert write_new(dest, b"thumb-bytes") is True
        assert dest.read_bytes() == b"thumb-bytes"
        assert not dest.is_symlink()
        assert _names(dest.parent) == [dest.name]
        if dangling:
            assert not victim.exists()
        else:
            assert victim.read_bytes() == b"victim"

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


class TestTempFdGuard:
    """SAN-003.1.3: a failing `os.fdopen` can't leak the fd or leave the temp behind."""

    @pytest.fixture
    def failing_fdopen(self, monkeypatch: pytest.MonkeyPatch) -> list[int]:
        opened: list[int] = []
        real_open = os.open

        def spy_open(*args: object, **kwargs: object) -> int:
            fd = real_open(*args, **kwargs)  # type: ignore[arg-type]
            if str(args[0]).endswith(".tmp"):
                opened.append(fd)
            return fd

        real_fdopen = os.fdopen

        def failing(fd: int, *args: object, **kwargs: object) -> object:
            if fd in opened:  # only the temp's fd fails; the source open is real
                raise OSError(24, "qorvex-planted-path")
            return real_fdopen(fd, *args, **kwargs)

        monkeypatch.setattr(os, "open", spy_open)
        monkeypatch.setattr(os, "fdopen", failing)
        return opened

    def _assert_closed(self, fd: int) -> None:
        with pytest.raises(OSError) as closed:
            os.fstat(fd)
        assert closed.value.errno == errno.EBADF

    def test_make_working_copy_closes_the_fd_and_leaves_no_temp(
        self, source: Path, work_dir: Path, failing_fdopen: list[int]
    ) -> None:
        with pytest.raises(OSError) as raised:
            make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert str(raised.value) == TEMP_FAILED
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        self._assert_closed(failing_fdopen[0])
        assert list(work_dir.iterdir()) == []

    def test_write_new_closes_the_fd_and_leaves_no_temp(
        self, work_dir: Path, failing_fdopen: list[int]
    ) -> None:
        work_dir.mkdir()
        dest = work_dir / f"{HASH}.webp"
        with pytest.raises(OSError) as raised:
            write_new(dest, b"x")
        assert str(raised.value) == TEMP_FAILED
        assert raised.value.__cause__ is None
        assert raised.value.__context__ is None
        self._assert_closed(failing_fdopen[0])
        assert list(work_dir.iterdir()) == []

    @pytest.mark.parametrize("code", [errno.EEXIST, errno.EACCES])
    def test_a_failing_temp_open_is_fixed_text(
        self, source: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch, code: int
    ) -> None:
        # SAN-003.1.5: the OSError of the temp open carries the path; it must not escape
        real_open = os.open

        def failing_open(path: object, *args: object, **kwargs: object) -> int:
            if str(path).endswith(".tmp"):
                raise OSError(code, "qorvex-planted", str(path))
            return real_open(path, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(os, "open", failing_open)
        with pytest.raises(OSError) as raised:
            make_working_copy(source, work_dir, HASH, "jpg", _no_op)
        assert str(raised.value) == TEMP_FAILED and raised.value.filename is None
        assert raised.value.__cause__ is None and raised.value.__context__ is None
        assert list(work_dir.iterdir()) == []

    def test_a_failing_pre_open_unlink_is_fixed_text(
        self, work_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        work_dir.mkdir()
        dest = work_dir / f"{HASH}.webp"

        def failing_unlink(self: Path, missing_ok: bool = False) -> None:
            raise PermissionError(errno.EACCES, "qorvex-planted", str(self))

        monkeypatch.setattr(Path, "unlink", failing_unlink)
        with pytest.raises(OSError) as raised:
            write_new(dest, b"x")
        assert str(raised.value) == TEMP_FAILED and raised.value.filename is None
        assert raised.value.__cause__ is None and raised.value.__context__ is None

    def test_a_failing_close_in_the_source_refusal_is_still_the_fixed_refusal(
        self, tmp_path: Path, work_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        folder = tmp_path / "qorvex-folder"
        folder.mkdir()  # opens fine, then fstat refuses it, so the refusal branch closes the fd
        real_close = os.close

        def failing_close(fd: int) -> None:
            real_close(fd)
            raise OSError(errno.EIO, "qorvex-planted", str(folder))

        monkeypatch.setattr(os, "close", failing_close)
        with pytest.raises(SourceRefusedError) as raised:
            make_working_copy(folder, work_dir, HASH, "jpg", _no_op)
        assert str(raised.value) == SOURCE_REFUSED
        assert raised.value.__cause__ is None and raised.value.__context__ is None
