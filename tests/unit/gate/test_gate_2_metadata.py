"""TST-005.2.2: gate 2's metadata judge and its seeded synthetic images (SAN-001.D3, D4, D13,
D15; TST-005.D7).

Synthetic images only, generated here and seeded through exiftool, as SAN-001.2's tests do.
The judge gets a stand-in structure predicate; the real `is_structure_tag` comes with #56.
"""

import importlib.util
import shutil
from pathlib import Path

import pytest

from classifier.sanitize.exif import Tag, read_tags, strip_metadata
from classifier.sanitize.rules import LOG_KEY_ENV, ExifFieldRule, ExifSettings, Rules, log_key

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "gate_2.py"
spec = importlib.util.spec_from_file_location("gate_2", SCRIPT)
assert spec and spec.loader
gate_2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_2)

KEY = log_key({LOG_KEY_ENV: "00112233445566778899aabbccddeeff"})
KEEP = ["Orientation", "DateTimeOriginal"]


def structure(tag: Tag) -> bool:
    """A stand-in for exif.py's predicate: ICC, Adobe and two size tags."""
    return (
        tag.group0 == "ICC_Profile"
        or tag.group1 == "Adobe"
        or (tag.group1, tag.name) in {("File", "ImageWidth"), ("IFD0", "ImageWidth")}
    )


def allowed(tag: Tag, dropped: tuple[str, ...] = ()) -> bool:
    return gate_2.tag_allowed(tag, KEEP, dropped, structure)


# --- the judge ---------------------------------------------------------------------------


def test_keep_list_tags_are_allowed_by_bare_or_grouped_name() -> None:
    assert allowed(Tag("EXIF", "IFD0", "Orientation", "6"))
    assert gate_2.tag_allowed(
        Tag("EXIF", "ExifIFD", "DateTimeOriginal", "x"), ["ExifIFD:DateTimeOriginal"], (), structure
    )


def test_structure_icc_and_adobe_tags_are_allowed() -> None:
    assert allowed(Tag("File", "File", "ImageWidth", "24"))
    assert allowed(Tag("ICC_Profile", "ICC-header", "ProfileVersion", "2"))
    assert allowed(Tag("APP14", "Adobe", "ColorTransform", "0"))


def test_an_exif_field_rule_beats_the_keep_list_but_not_structure() -> None:
    """SAN-001.D15."""
    assert not allowed(Tag("EXIF", "IFD0", "Orientation", "6"), ("Orientation",))
    assert allowed(Tag("EXIF", "IFD0", "ImageWidth", "24"), ("ImageWidth",))


@pytest.mark.parametrize(
    "tag",
    [
        Tag("EXIF", "IFD0", "Artist", "x"),
        Tag("EXIF", "GPS", "GPSLatitude", "1"),
        Tag("XMP", "XMP-dc", "Creator", "x"),
        Tag("IPTC", "IPTC", "By-line", "x"),
        Tag("PNG", "PNG", "Some Free Keyword", "x"),
        Tag("XMP", "XMP-orientation", "Thing", "x"),  # a group that merely contains a keep word
    ],
)
def test_any_other_tag_fails(tag: Tag) -> None:
    assert not allowed(tag)
    width = Tag("File", "File", "ImageWidth", "1")
    assert not gate_2.output_clean([width, tag], KEEP, (), structure)


def test_markers_are_found_in_utf8_and_utf16() -> None:
    marker = "G2SEED00x0123456789"
    for encoding in ("utf-8", "utf-16-le", "utf-16-be"):
        assert gate_2.carries_marker(b"\x00ab" + marker.encode(encoding) + b"cd", [marker])
    assert not gate_2.carries_marker(b"G2SEED00x012345678", [marker])


@pytest.mark.parametrize(
    ("inputs", "sanitized", "clean", "line", "end"),
    [
        (7, 7, 7, "100.0% sanitized, 100.0% of outputs clean", "ok"),
        (7, 6, 6, "85.7% sanitized, 100.0% of outputs clean", "FAIL"),
        (7, 7, 6, "100.0% sanitized, 85.7% of outputs clean", "FAIL"),
        (1000, 999, 999, "99.9% sanitized, 100.0% of outputs clean", "FAIL"),
        (3, 0, 0, "0.0% sanitized, 0.0% of outputs clean", "FAIL"),
    ],
)
def test_the_metadata_line(inputs: int, sanitized: int, clean: int, line: str, end: str) -> None:
    ok, text = gate_2.judge_metadata("synthetic", inputs, sanitized, clean)
    assert text == f"metadata, synthetic: {line} (required 100.0% and 100.0%): {end}"
    assert ok is (end == "ok")


def test_an_empty_set_fails() -> None:
    assert gate_2.judge_metadata("real fixtures", 0, 0, 0) == (
        False,
        "metadata, real fixtures: nothing reached the sanitize node: FAIL",
    )


# --- the synthetic set, against SAN-001.2's real strip ------------------------------------


@pytest.fixture
def seeded(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    folder = tmp_path / "set"
    folder.mkdir()
    return folder, gate_2.make_seeded_images(folder)


def test_every_synthetic_image_carries_its_markers(seeded: tuple[Path, tuple[str, ...]]) -> None:
    folder, markers = seeded
    files = sorted(folder.iterdir())
    assert len(files) == len(gate_2.SYNTHETIC_FORMATS)
    assert len(set(markers)) == len(markers) == len(files) * len(gate_2.MARKED_TAGS)
    groups: set[str] = set()
    names: set[str] = set()
    for path in files:
        assert gate_2.carries_marker(path.read_bytes(), markers)
        tags = read_tags(path).entries
        groups |= {tag.group0 for tag in tags}
        names |= {tag.name for tag in tags}
        assert not gate_2.output_clean(tags, KEEP, (), structure)
    assert {"EXIF", "XMP", "IPTC", "ICC_Profile"} <= groups
    assert {"GPSLatitude", "Orientation", "DateTimeOriginal", "ColorTransform"} <= names


def test_the_draw_of_markers_is_pinned(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    assert gate_2.make_seeded_images(tmp_path / "a") == gate_2.make_seeded_images(tmp_path / "b")


def test_no_marker_survives_the_real_strip(
    seeded: tuple[Path, tuple[str, ...]], tmp_path: Path
) -> None:
    folder, markers = seeded
    rules = Rules(exif=ExifSettings(mode="strip_all", keep=KEEP), rules=(), log_key=KEY)
    for path in sorted(folder.iterdir()):
        copy = tmp_path / f"copy{path.suffix}"
        shutil.copyfile(path, copy)
        strip_metadata(copy, rules)
        assert not gate_2.carries_marker(copy.read_bytes(), markers)
        left = {tag.name for tag in read_tags(copy).entries}
        assert not left & {"Artist", "GPSLatitude", "Creator", "By-line", "Comment"}


def test_an_exif_field_rule_on_a_kept_tag_shows_in_the_judge(
    seeded: tuple[Path, tuple[str, ...]], tmp_path: Path
) -> None:
    """The real strip honours D15; the gate's judge agrees on the same read-back."""
    folder, _ = seeded
    drop = ExifFieldRule(id="no-orientation", type="exif_field", fields=["Orientation"])
    rules = Rules(exif=ExifSettings(mode="strip_all", keep=KEEP), rules=(drop,), log_key=KEY)
    copy = tmp_path / "copy.jpg"
    shutil.copyfile(folder / "synthetic_00.jpg", copy)
    strip_metadata(copy, rules)
    entries = read_tags(copy).entries
    assert "Orientation" not in {tag.name for tag in entries}
    kept = [t for t in entries if t.name == "DateTimeOriginal"]
    assert kept and all(gate_2.tag_allowed(t, KEEP, ("Orientation",), structure) for t in kept)


def test_a_broken_exiftool_fails_the_seeding_naming_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(gate_2.GateSetupError) as caught:
        gate_2.make_seeded_images(tmp_path)
    assert "exiftool" in str(caught.value) and caught.value.__context__ is None
