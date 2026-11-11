"""API-001.3.2: the thumbnail reader (m4 privacy item 13, API-001.D12).

Synthetic webp files in `tmp_path` only. Each refusal's plant is proved readable or present
first, so the None it gets could have been bytes.
"""

import hashlib
import io
import os
from pathlib import Path

import pytest
from PIL import Image

from classifier.api import thumbs
from classifier.api.thumbs import (
    MAX_THUMB_BYTES,
    THUMB_SUFFIX,
    is_source_hash,
    read_thumbnail,
    thumbs_folder,
)
from classifier.graph import sanitize

SECRET = "Zhyndel-planted-secret"


def _hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _webp() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (8, 8), (40, 90, 160)).save(out, format="WEBP")
    return out.getvalue()


def _results(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "results"
    folder = root / ".work" / "thumbs"
    folder.mkdir(parents=True)
    return root, folder


def test_folder_names_are_the_sanitize_nodes() -> None:
    """The API's copies can't drift from ING-002.D1's `.work/thumbs/<source_hash>.webp`."""
    assert (thumbs.WORK_DIR, thumbs.THUMBS_DIR) == (sanitize.WORK_DIR, sanitize.THUMBS_DIR)
    assert THUMB_SUFFIX == ".webp"


@pytest.mark.parametrize(
    ("value", "ok"),
    [
        (_hash("a"), True),
        (_hash("a").upper(), False),
        (_hash("a")[:63], False),
        (_hash("a") + "0", False),
        ("../" + _hash("a")[3:], False),
        ("", False),
    ],
)
def test_is_source_hash(value: str, ok: bool) -> None:
    assert is_source_hash(value) is ok


def test_reads_a_regular_thumbnail(tmp_path: Path) -> None:
    root, folder = _results(tmp_path)
    h, data = _hash("a"), _webp()
    (folder / f"{h}.webp").write_bytes(data)
    assert read_thumbnail(root, h) == data


def test_missing_file(tmp_path: Path) -> None:
    root, _ = _results(tmp_path)
    assert read_thumbnail(root, _hash("absent")) is None


def test_symlink_is_refused(tmp_path: Path) -> None:
    root, folder = _results(tmp_path)
    target = tmp_path / "elsewhere.webp"
    target.write_bytes(_webp())
    h = _hash("link")
    (folder / f"{h}.webp").symlink_to(target)
    assert (folder / f"{h}.webp").read_bytes() == target.read_bytes()  # the link does work
    assert read_thumbnail(root, h) is None


def test_directory_is_refused(tmp_path: Path) -> None:
    root, folder = _results(tmp_path)
    h = _hash("dir")
    (folder / f"{h}.webp").mkdir()
    assert (folder / f"{h}.webp").exists()
    assert read_thumbnail(root, h) is None


def test_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    root, folder = _results(tmp_path)
    h = _hash("fifo")
    os.mkfifo(folder / f"{h}.webp")
    assert (folder / f"{h}.webp").exists()
    assert read_thumbnail(root, h) is None  # O_NONBLOCK: a blocking open would hang here


def test_oversized_is_refused(tmp_path: Path) -> None:
    root, folder = _results(tmp_path)
    h = _hash("big")
    (folder / f"{h}.webp").write_bytes(b"\0" * (MAX_THUMB_BYTES + 1))
    assert read_thumbnail(root, h) is None
    (folder / f"{h}.webp").write_bytes(b"\0" * MAX_THUMB_BYTES)  # the cap itself is allowed
    assert read_thumbnail(root, h) is not None


def test_linked_thumbs_folder_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "results"
    (root / ".work").mkdir(parents=True)
    real = tmp_path / "real-thumbs"
    real.mkdir()
    h = _hash("redirected")
    (real / f"{h}.webp").write_bytes(_webp())
    (root / ".work" / "thumbs").symlink_to(real, target_is_directory=True)
    assert (root / ".work" / "thumbs" / f"{h}.webp").is_file()  # reachable through the link
    assert thumbs_folder(root) is None
    assert read_thumbnail(root, h) is None


def test_linked_work_folder_is_refused(tmp_path: Path) -> None:
    root = tmp_path / "results"
    root.mkdir()
    real = tmp_path / "real-work"
    (real / "thumbs").mkdir(parents=True)
    h = _hash("work")
    (real / "thumbs" / f"{h}.webp").write_bytes(_webp())
    (root / ".work").symlink_to(real, target_is_directory=True)
    assert (root / ".work" / "thumbs" / f"{h}.webp").is_file()
    assert read_thumbnail(root, h) is None


def test_no_results_folder(tmp_path: Path) -> None:
    assert thumbs_folder(tmp_path / "absent") is None
    assert read_thumbnail(tmp_path / "absent", _hash("a")) is None


def test_bad_hash_never_touches_the_filesystem(tmp_path: Path, monkeypatch) -> None:
    root, _ = _results(tmp_path)
    touched: list[object] = []
    monkeypatch.setattr(thumbs.os, "open", lambda *a, **k: touched.append(a) or 0)
    assert read_thumbnail(root, "../" + _hash("a")[3:]) is None
    assert touched == []


def test_oserror_is_none_with_no_exception_kept(tmp_path: Path, monkeypatch) -> None:
    root, folder = _results(tmp_path)
    h = _hash("oserror")
    (folder / f"{h}.webp").write_bytes(_webp())
    error = PermissionError(13, SECRET, f"/results/{SECRET}")
    assert SECRET in str(error)  # the plant is in the OS error

    def refuse(*_args: object, **_kwargs: object) -> int:
        raise error

    monkeypatch.setattr(thumbs.os, "open", refuse)
    assert read_thumbnail(root, h) is None
