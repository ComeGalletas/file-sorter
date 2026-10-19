"""CLS-002.2.2: the working-copy opener and the name it shares with sanitize.

Synthetic images only, generated in code. The privacy cases plant an artificial coinage in
a path and check it never reaches an error or a chain (privacy checklist 5, 6).
"""

import os
from pathlib import Path

import pytest
from PIL import Image

from classifier.fileops.copy_move import make_working_copy, working_copy_name
from classifier.graph.classify import (
    WORKING_COPY_UNREADABLE,
    WorkingCopyUnreadable,
    first_frame_rgb,
    open_working_frames,
)

HASH = "ab" * 32
OTHER = "cd" * 32
SECRET = "Qorvex-Zhyndel"  # an artificial coinage, planted to prove it never leaks


def _open_rgb(work: Path, source_hash: str, ext: str) -> Image.Image:
    """What the node does: open the working copy once, take frame 0 as RGB."""
    with open_working_frames(work, source_hash, ext) as image:
        return first_frame_rgb(image)


def _png(path: Path, size: tuple[int, int] = (6, 4), color=(200, 30, 40)) -> None:
    Image.new("RGB", size, color).save(path, "PNG")


# --- the shared working-copy name (CLS-002.D8) ---------------------------------------------


def test_sanitize_and_classify_agree_on_the_name(tmp_path: Path) -> None:
    source = tmp_path / "in.png"
    _png(source)
    work = tmp_path / ".work"
    copy = make_working_copy(source, work, HASH, "png", lambda tmp: None)
    assert copy.path.name == working_copy_name(HASH, "png")
    assert _open_rgb(work, HASH, "png").size == (6, 4)


@pytest.mark.parametrize(
    ("source_hash", "ext"),
    [
        ("short", "png"),
        (HASH.upper(), "png"),
        (HASH, "../x"),
        (HASH, "p/g"),
        (HASH, ""),
        (HASH, ".png"),
    ],
)
def test_name_refuses_bad_hash_or_ext_with_fixed_text(source_hash: str, ext: str) -> None:
    with pytest.raises(ValueError) as caught:
        working_copy_name(source_hash, ext)
    assert "must be" in str(caught.value)
    assert "../" not in str(caught.value)  # fixed text: the value is never quoted


# --- the opener ---------------------------------------------------------------------------


def test_opens_a_png_as_rgb(tmp_path: Path) -> None:
    _png(tmp_path / working_copy_name(HASH, "png"), (7, 5))
    image = _open_rgb(tmp_path, HASH, "png")
    assert image.mode == "RGB"
    assert image.size == (7, 5)


def test_converts_palette_and_alpha_to_rgb(tmp_path: Path) -> None:
    Image.new("RGBA", (3, 3), (1, 2, 3, 4)).save(tmp_path / working_copy_name(HASH, "png"))
    Image.new("P", (3, 3)).save(tmp_path / working_copy_name(OTHER, "gif"))
    assert _open_rgb(tmp_path, HASH, "png").mode == "RGB"
    assert _open_rgb(tmp_path, OTHER, "gif").mode == "RGB"


def test_takes_only_the_first_frame(tmp_path: Path) -> None:  # R-ING-6
    frames = [Image.new("RGB", (4, 4), c) for c in ((255, 0, 0), (0, 0, 255))]
    frames[0].save(
        tmp_path / working_copy_name(HASH, "gif"), save_all=True, append_images=frames[1:]
    )
    image = _open_rgb(tmp_path, HASH, "gif")
    red, _green, blue = image.getpixel((0, 0))
    assert red > blue


def _refused(work: Path, source_hash: str = HASH, ext: str = "png") -> WorkingCopyUnreadable:
    with pytest.raises(WorkingCopyUnreadable) as caught:
        _open_rgb(work, source_hash, ext)
    return caught.value


def test_missing_file_is_refused_with_the_fixed_reason(tmp_path: Path) -> None:
    error = _refused(tmp_path)
    assert error.reason == WORKING_COPY_UNREADABLE == str(error)


def test_symlink_is_refused_even_to_a_valid_image(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.png"
    _png(target)
    (tmp_path / working_copy_name(HASH, "png")).symlink_to(target)
    _refused(tmp_path)


def test_directory_is_refused(tmp_path: Path) -> None:
    (tmp_path / working_copy_name(HASH, "png")).mkdir()
    _refused(tmp_path)


def test_fifo_is_refused_without_blocking(tmp_path: Path) -> None:
    os.mkfifo(tmp_path / working_copy_name(HASH, "png"))
    _refused(tmp_path)


def test_truncated_and_garbage_files_are_refused(tmp_path: Path) -> None:
    good = tmp_path / "good.png"
    _png(good, (40, 40))
    (tmp_path / working_copy_name(HASH, "png")).write_bytes(good.read_bytes()[:30])
    (tmp_path / working_copy_name(OTHER, "png")).write_bytes(b"not an image")
    _refused(tmp_path)
    _refused(tmp_path, OTHER)


def test_bad_hash_or_ext_is_refused_the_same_way(tmp_path: Path) -> None:
    _refused(tmp_path, "../" + HASH[3:], "png")
    _refused(tmp_path, HASH, "../png")


def test_error_is_unchained_and_carries_no_path(tmp_path: Path) -> None:
    work = tmp_path / SECRET
    work.mkdir()
    (work / working_copy_name(HASH, "png")).write_bytes(b"junk")
    for folder in (work, tmp_path / (SECRET + "-missing")):
        error = _refused(folder)
        assert error.__cause__ is None
        assert error.__context__ is None
        assert SECRET not in str(error) + repr(error)
        assert str(tmp_path) not in str(error) + repr(error)


def test_opened_image_is_independent_of_the_file(tmp_path: Path) -> None:
    path = tmp_path / working_copy_name(HASH, "png")
    _png(path)
    image = _open_rgb(tmp_path, HASH, "png")
    path.unlink()
    assert image.getpixel((0, 0)) == (200, 30, 40)  # pixels were loaded before the close


# --- one read, every frame (CLS-004.4) ----------------------------------------------------


def _gif(path: Path, colors: tuple[tuple[int, int, int], ...]) -> None:
    frames = [Image.new("RGB", (4, 4), c) for c in colors]
    frames[0].save(path, save_all=True, append_images=frames[1:])


def test_frames_stay_seekable_after_the_file_is_gone(tmp_path: Path) -> None:
    path = tmp_path / working_copy_name(HASH, "gif")
    _gif(path, ((255, 0, 0), (0, 255, 0), (0, 0, 255)))
    image = open_working_frames(tmp_path, HASH, "gif")
    path.unlink()  # the bytes are in memory: the descriptor is long closed
    assert image.n_frames == 3
    image.seek(2)
    assert image.convert("RGB").getpixel((0, 0))[2] > 200


def test_first_frame_rgb_comes_from_the_same_image(tmp_path: Path) -> None:
    _gif(tmp_path / working_copy_name(HASH, "gif"), ((255, 0, 0), (0, 0, 255)))
    image = open_working_frames(tmp_path, HASH, "gif")
    image.seek(1)  # wherever the VLM client left it
    frame = first_frame_rgb(image)
    assert frame.mode == "RGB"
    red, _green, blue = frame.getpixel((0, 0))
    assert red > blue
    assert image.tell() == 0


def test_frames_opener_keeps_the_refusals_and_the_fixed_reason(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere.png"
    _png(target)
    (tmp_path / working_copy_name(HASH, "png")).symlink_to(target)  # a link
    (tmp_path / working_copy_name(OTHER, "png")).write_bytes(b"not an image")
    for source_hash in (HASH, OTHER, "ef" * 32):  # link, garbage, missing
        with pytest.raises(WorkingCopyUnreadable) as caught:
            open_working_frames(tmp_path, source_hash, "png")
        assert str(caught.value) == WORKING_COPY_UNREADABLE
        assert caught.value.__cause__ is None
        assert caught.value.__context__ is None
        assert str(tmp_path) not in str(caught.value) + repr(caught.value)
