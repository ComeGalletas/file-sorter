"""SAN-003.2.1: the image libraries can't log or warn a value (SAN-001.D16, SAN-003.D4).

Synthetic images only. Every secret is a made-up coinage that must appear nowhere.
"""

import logging
import warnings
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin
from pillow_heif import register_heif_opener

from classifier.fileops import thumbs
from classifier.fileops.image_output import LIBRARY_LOGGERS, cap_image_library_output

register_heif_opener()

SECRET = "Zyxwq-Plonk-Artist-4242"
HASH = "ab" * 32
ARTIST = 0x013B


@pytest.fixture(autouse=True)
def restore_loggers() -> None:
    """Start each test with the library loggers uncapped, and put them back after."""
    saved = {name: logging.getLogger(name).level for name in LIBRARY_LOGGERS}
    for name in LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)
    yield
    for name, level in saved.items():
        logging.getLogger(name).setLevel(level)


def tagged_image(path: Path, fmt: str) -> Path:
    image = Image.new("RGB", (24, 16), (10, 200, 30))
    if fmt == "PNG":
        info = PngImagePlugin.PngInfo()
        info.add_text("Comment", SECRET)
        image.save(path, "PNG", pnginfo=info)
    else:
        exif = Image.Exif()
        exif[ARTIST] = SECRET
        image.save(path, fmt, exif=exif.tobytes())
    return path


def test_the_loggers_are_held_at_info() -> None:
    cap_image_library_output()
    for name in LIBRARY_LOGGERS:
        assert logging.getLogger(name).level == logging.INFO


@pytest.mark.parametrize("name", ["pillow_heif", "pillow_heif.heif", "PIL.Image", "PIL"])
def test_a_library_debug_record_is_dropped_under_root_debug(
    name: str, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    cap_image_library_output()
    logging.getLogger(name).debug("tag value %s", SECRET)
    assert SECRET not in caplog.text
    assert not caplog.records


def test_our_own_loggers_still_log_under_debug(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    cap_image_library_output()
    logging.getLogger("classifier.graph.sanitize").debug("fixed text")
    assert "fixed text" in caplog.text


@pytest.mark.parametrize("fmt, ext", [("HEIF", "heic"), ("PNG", "png")])
def test_decoding_and_thumbnailing_log_no_value_under_debug(
    fmt: str, ext: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    path = tagged_image(tmp_path / f"work.{ext}", fmt)
    caplog.set_level(logging.DEBUG)
    cap_image_library_output()

    with Image.open(path) as image:
        image.load()
        image.getexif()
    thumbs.make_thumbnail(path, tmp_path, HASH, 16)

    assert SECRET not in caplog.text
    assert not [r for r in caplog.records if r.name.split(".")[0] in LIBRARY_LOGGERS]


def test_the_cap_is_what_holds_the_record_back(caplog: pytest.LogCaptureFixture) -> None:
    # Control: without the cap the same record is captured, so the tests above can fail.
    caplog.set_level(logging.DEBUG)
    logging.getLogger("pillow_heif").debug("tag value %s", SECRET)
    assert SECRET in caplog.text


def library_warning(module: str) -> None:
    """Warn from a frame whose `__name__` is `module`, as a library plugin would."""
    code = compile(f"import warnings\nwarnings.warn({SECRET!r})", "<planted>", "exec")
    exec(code, {"__name__": module})  # noqa: S102 - synthetic text, no input


@pytest.mark.parametrize("module", ["PIL.Image", "PIL.TiffImagePlugin", "pillow_heif.as_plugin"])
def test_a_library_warning_is_ignored(module: str, recwarn: pytest.WarningsRecorder) -> None:
    cap_image_library_output()
    library_warning(module)
    assert not [w for w in recwarn if SECRET in str(w.message)]


def test_a_real_decompression_bomb_warning_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    path = tagged_image(tmp_path / "work.png", "PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300)  # 384 px: past the limit, under 2x
    cap_image_library_output()
    with Image.open(path) as image:
        image.load()
    assert not [w for w in recwarn if issubclass(w.category, Image.DecompressionBombWarning)]


def test_the_bomb_warning_shows_without_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, recwarn: pytest.WarningsRecorder
) -> None:
    # Control for the test above.
    path = tagged_image(tmp_path / "work.png", "PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 300)
    with Image.open(path) as image:
        image.load()
    assert [w for w in recwarn if issubclass(w.category, Image.DecompressionBombWarning)]


def test_a_bomb_past_twice_the_limit_still_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tagged_image(tmp_path / "work.png", "PNG")
    monkeypatch.setattr(Image, "MAX_IMAGE_PIXELS", 100)  # 384 px is past 2x
    cap_image_library_output()
    with pytest.raises(Image.DecompressionBombError), Image.open(path):
        pass


def test_a_warning_from_our_own_code_still_shows(recwarn: pytest.WarningsRecorder) -> None:
    cap_image_library_output()
    library_warning("classifier.fileops.thumbs")
    assert [w for w in recwarn if SECRET in str(w.message)]


def test_calling_it_twice_adds_one_filter() -> None:
    with warnings.catch_warnings():
        before = len(warnings.filters)
        cap_image_library_output()
        once = len(warnings.filters)
        cap_image_library_output()
        assert once == before + 1
        assert len(warnings.filters) == once
