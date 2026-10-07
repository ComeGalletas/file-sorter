"""SAN-001.2: lossless metadata strip and read-back (SAN-001.D3, D4, D11–D15).

Synthetic images only, generated here and seeded with made-up tag values through exiftool.
"""

import logging
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms, PngImagePlugin
from pillow_heif import register_heif_opener

from classifier.db.models import SanitizeLog
from classifier.sanitize import exif
from classifier.sanitize.exif import (
    RESIDUAL_REASON,
    STRIP_ALL_RULE_ID,
    MetadataStripError,
    Tag,
    Tags,
    log_field,
    read_tags,
    strip_metadata,
)
from classifier.sanitize.rules import (
    LOG_KEY_ENV,
    ExifFieldRule,
    ExifSettings,
    Rules,
    before_hash,
    log_key,
)

register_heif_opener()

KEY = log_key({LOG_KEY_ENV: "00112233445566778899aabbccddeeff"})


def db_field_check() -> re.Pattern[str]:
    """The exif pattern of DB-002.D1's sanitize_log.field check, read from the model."""
    (check,) = (c for c in SanitizeLog.__table__.constraints if c.name == "sanitize_log_field")
    (pattern,) = re.findall(r"field ~ '([^']+)'", str(check.sqltext))
    return re.compile(pattern)


DB_FIELD_CHECK = db_field_check()  # SAN-001.D14 must fit it


def test_the_db_field_check_is_the_exif_pattern() -> None:
    assert DB_FIELD_CHECK.pattern.startswith("^exif:")
    assert DB_FIELD_CHECK.fullmatch("exif:EXIF:GPSLatitude")
    assert not DB_FIELD_CHECK.fullmatch("exif:EXIF:Zyxwq Plonk")


# Made-up values that must never surface anywhere but a hash.
SECRETS = {
    "Artist": "Zyxwq Plonk Artist",
    "Software": "Zyxwq Plonk Software",
    "Copyright": "Zyxwq Plonk Copyright",
    "ImageDescription": "Zyxwq Plonk Description",
    "SerialNumber": "ZYXWQ-SERIAL-4242",
    "XMP-dc:Creator": "Zyxwq Plonk Creator",
    "IPTC:By-line": "Zyxwq Plonk Byline",
    "Comment": "Zyxwq Plonk Comment",
}
OPTION_LIKE = "-delete_original!"  # a value that reads as an exiftool option
GPS = ("-GPSLatitude=12.3456", "-GPSLatitudeRef=N", "-GPSLongitude=65.4321", "-GPSLongitudeRef=W")
KEEP_SEED = ("-Orientation#=6", "-DateTimeOriginal=2020:01:02 03:04:05")
NEVER_SURVIVES = {"Artist", "Software", "Copyright", "ImageDescription", "SerialNumber",
                  "Creator", "By-line", "Comment", "GPSLatitude", "GPSLongitude"}  # fmt: skip

FORMATS = {"jpg": "JPEG", "png": "PNG", "webp": "WEBP", "gif": "GIF", "tif": "TIFF", "heic": "HEIF"}
SRGB = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()


def rules(keep: list[str] | None = None, drops: tuple[ExifFieldRule, ...] = ()) -> Rules:
    if keep is None:
        keep = ["Orientation", "DateTimeOriginal"]
    return Rules(exif=ExifSettings(mode="strip_all", keep=keep), rules=drops, log_key=KEY)


def picture() -> Image.Image:
    image = Image.new("RGB", (24, 16), (10, 200, 30))
    for x in range(24):
        image.putpixel((x, 5), (x * 10, 0, 255))
        image.putpixel((x, 9), (255, x * 10, 0))
    return image


def make_image(path: Path, fmt: str) -> Path:
    image = picture()
    options: dict[str, object] = {}
    if fmt != "GIF":
        options["icc_profile"] = SRGB
    if fmt == "WEBP":
        options["lossless"] = True
    (image.convert("P") if fmt == "GIF" else image).save(path, fmt, **options)
    return path


def seed(path: Path, *extra: str) -> None:
    values = [f"-{tag}={value}" for tag, value in SECRETS.items()]
    done = subprocess.run(
        ["exiftool", "-m", "-q", "-q", "-overwrite_original", *values, *GPS, *KEEP_SEED,
         *extra, str(path)],
        capture_output=True,
        check=False,
    )  # fmt: skip
    assert done.returncode == 0, "seeding the synthetic image failed"


def seeded(tmp_path: Path, ext: str) -> Path:
    path = make_image(tmp_path / f"work image.{ext}", FORMATS[ext])
    seed(path)
    return path


def pixels(path: Path) -> tuple[str, tuple[int, int], bytes]:
    with Image.open(path) as image:
        return image.mode, image.size, image.tobytes()


def icc(path: Path) -> bytes:
    return subprocess.run(
        ["exiftool", "-b", "-ICC_Profile", str(path)], capture_output=True, check=True
    ).stdout


def names(tags: Tags) -> set[str]:
    return {tag.name for tag in tags.entries}


def surfaces(*objects: object) -> str:
    return "\n".join(f"{obj!r}\n{obj!s}" for obj in objects)


def assert_clean(text: str) -> None:
    for secret in (*SECRETS.values(), "12.3456", "65.4321"):
        assert secret not in text


def spy_on_exiftool(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    real = exif._exiftool

    def spy(args: list[str]) -> subprocess.CompletedProcess[bytes] | None:
        calls.append(args)
        return real(args)

    monkeypatch.setattr(exif, "_exiftool", spy)
    return calls


# --- read_tags ---------------------------------------------------------------------------


def test_read_tags_sees_seeded_tags_and_skips_file_system_groups(tmp_path: Path) -> None:
    tags = read_tags(seeded(tmp_path, "jpg"))
    assert tags.file_type == "JPEG"
    assert {"Artist", "GPSLatitude", "Creator", "By-line", "Orientation"} <= names(tags)
    assert not {"FileName", "Directory", "ExifToolVersion"} & names(tags)
    groups = {(tag.group0, tag.group1) for tag in tags.entries}
    assert ("EXIF", "GPS") in groups and ("XMP", "XMP-dc") in groups


def test_tags_repr_shows_no_name_or_value(tmp_path: Path) -> None:
    tags = read_tags(seeded(tmp_path, "jpg"))
    text = surfaces(tags, *tags.entries)
    assert_clean(text)
    assert "Artist" not in text and "GPSLatitude" not in text
    assert re.fullmatch(r"Tags\(file_type='JPEG', count=\d+\)", repr(tags))


@pytest.mark.parametrize(
    "stdout",
    [
        b'[{"SourceFile": "/w", "ExifTool:Error": "Zyxwq Plonk Artist", "IFD0:Artist": "x"}]',
        b"Zyxwq Plonk Artist: not json",
        b"[]",
        b'{"IFD0:Artist": "Zyxwq Plonk Artist"}',
    ],
)
def test_read_tags_fails_closed_on_an_error_or_unparseable_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdout: bytes
) -> None:
    path = make_image(tmp_path / "work.jpg", "JPEG")
    monkeypatch.setattr(
        exif, "_exiftool", lambda args: subprocess.CompletedProcess(args, 0, stdout, b"")
    )
    with pytest.raises(MetadataStripError) as caught:
        read_tags(path)
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert_clean(str(caught.value) + repr(caught.value))


def test_strip_fails_closed_on_a_non_image(tmp_path: Path) -> None:
    path = tmp_path / "text.jpg"  # exiftool reads it as TXT, and can't write it
    path.write_bytes(b"not an image " + SECRETS["Artist"].encode())
    with pytest.raises(MetadataStripError) as caught:
        strip_metadata(path, rules())
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert_clean(str(caught.value))


# --- log_field (SAN-001.D14, DB-002.D1) ----------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        (Tag("EXIF", "GPS", "GPSLatitude", "x"), "exif:EXIF:GPSLatitude"),
        (Tag("XMP", "XMP-dc", "Creator", "x"), "exif:XMP:Creator"),
        (Tag("IPTC", "IPTC", "By-line", "x"), "exif:IPTC:By-line"),
        (Tag("PNG", "PNG", "ZyxwqPlonkKeyword", "x"), "exif:PNG:unknown"),
        (Tag("EXIF", "IFD0", "Zyxwq Plonk", "x"), "exif:EXIF:unknown"),
        (Tag("Zyxwq Plonk", "Zyxwq Plonk", "Artist", "x"), "exif:unknown"),
        (Tag("EXIF", "IFD0", "Artist" + "x" * 80, "x"), "exif:EXIF:unknown"),
    ],
)
def test_log_field_names_only_tags_exiftool_knows(tag: Tag, expected: str) -> None:
    assert log_field(tag) == expected
    assert DB_FIELD_CHECK.fullmatch(log_field(tag))


# --- strip_metadata, per format -------------------------------------------------------------


@pytest.mark.parametrize("ext", sorted(FORMATS))
def test_strip_keeps_only_the_keep_list_icc_and_structure(tmp_path: Path, ext: str) -> None:
    path = seeded(tmp_path, ext)
    before = read_tags(path)
    original_pixels = pixels(path)
    original_icc = icc(path)

    redactions = strip_metadata(path, rules())

    after = read_tags(path)
    assert not NEVER_SURVIVES & names(after)
    assert {"Orientation", "DateTimeOriginal"} <= names(after)
    assert all(exif._allowed(tag, rules()) for tag in after.entries)
    assert pixels(path) == original_pixels
    assert icc(path) == original_icc
    if ext != "gif":
        assert original_icc  # the profile is really there, and kept (SAN-001.D4)

    assert redactions
    assert all(row.rule_id == STRIP_ALL_RULE_ID for row in redactions)
    assert all(row.after_value is None for row in redactions)
    assert all(DB_FIELD_CHECK.fullmatch(row.field) for row in redactions)
    hashes = {row.before_hash for row in redactions}
    assert before_hash(SECRETS["XMP-dc:Creator"], KEY) in hashes
    seeded_values = {t.value for t in before.entries if t.name in NEVER_SURVIVES}
    assert seeded_values
    assert {before_hash(value, KEY) for value in seeded_values} <= hashes
    assert_clean(surfaces(redactions, *(row.field for row in redactions)))


def test_tiff_ifd0_leftovers_are_removed_by_the_second_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = seeded(tmp_path, "tif")
    calls = spy_on_exiftool(monkeypatch)
    strip_metadata(path, rules())
    targeted = {arg for args in calls for arg in args if arg.startswith("-IFD0:")}
    assert "-IFD0:Artist=" in targeted
    assert not {"-IFD0:ImageWidth=", "-IFD0:StripOffsets="} & targeted
    assert not {"Artist", "Software"} & names(read_tags(path))


def test_bmp_is_left_as_is_and_checked_by_read_back(tmp_path: Path) -> None:
    path = tmp_path / "plain.bmp"
    picture().save(path, "BMP")
    data = path.read_bytes()
    assert strip_metadata(path, rules()) == []
    assert path.read_bytes() == data


def test_a_second_strip_is_a_no_op(tmp_path: Path) -> None:
    path = seeded(tmp_path, "jpg")
    strip_metadata(path, rules())
    first = pixels(path), read_tags(path).entries
    assert strip_metadata(path, rules()) == []
    assert (pixels(path), read_tags(path).entries) == first


def test_adobe_app14_is_kept_in_a_cmyk_jpeg(tmp_path: Path) -> None:
    path = tmp_path / "cmyk.jpg"
    picture().convert("CMYK").save(path, "JPEG", quality=95)
    seed(path)
    original = pixels(path)
    adobe = {t for t in read_tags(path).entries if t.group1 == "Adobe"}
    assert adobe  # Pillow writes APP14 for CMYK

    strip_metadata(path, rules())

    assert {t for t in read_tags(path).entries if t.group1 == "Adobe"} == adobe  # D13
    assert pixels(path) == original


def test_jfif_is_removed(tmp_path: Path) -> None:
    path = seeded(tmp_path, "jpg")
    assert any(t.group0 == "JFIF" for t in read_tags(path).entries)
    strip_metadata(path, rules())
    assert not any(t.group0 == "JFIF" for t in read_tags(path).entries)


def test_an_empty_keep_list_keeps_nothing_but_structure(tmp_path: Path) -> None:
    path = seeded(tmp_path, "png")
    strip_metadata(path, rules(keep=[]))
    assert not {"Orientation", "DateTimeOriginal"} & names(read_tags(path))


# --- exif_field rules (SAN-001.D11, D12, D15) -----------------------------------------------


def test_exif_field_beats_the_keep_list(tmp_path: Path) -> None:
    path = seeded(tmp_path, "jpg")
    drop = ExifFieldRule(id="no-orientation", type="exif_field", fields=["Orientation"])
    redactions = strip_metadata(path, rules(drops=(drop,)))
    assert "Orientation" not in names(read_tags(path))
    assert "DateTimeOriginal" in names(read_tags(path))
    rows = [row for row in redactions if row.field == "exif:EXIF:Orientation"]
    assert [row.rule_id for row in rows] == ["no-orientation"]


def test_exif_field_takes_its_own_rule_id_for_a_tag_outside_the_keep_list(
    tmp_path: Path,
) -> None:
    path = seeded(tmp_path, "jpg")
    drop = ExifFieldRule(id="no-gps", type="exif_field", fields=["GPS:GPSLatitude"])
    redactions = strip_metadata(path, rules(drops=(drop,)))
    by_field = {row.field: row.rule_id for row in redactions}
    assert by_field["exif:EXIF:GPSLatitude"] == "no-gps"
    assert by_field["exif:EXIF:GPSLongitude"] == STRIP_ALL_RULE_ID
    assert by_field["exif:EXIF:Artist"] == STRIP_ALL_RULE_ID


def test_exif_field_never_removes_a_structure_or_icc_tag(tmp_path: Path) -> None:
    path = make_image(tmp_path / "work.tif", "TIFF")
    original = pixels(path), icc(path)
    drop = ExifFieldRule(
        id="too-far", type="exif_field", fields=["ImageWidth", "StripOffsets", "ProfileDescription"]
    )
    strip_metadata(path, rules(drops=(drop,)))
    assert (pixels(path), icc(path)) == original
    assert {"ImageWidth", "StripOffsets", "ProfileDescription"} <= names(read_tags(path))


# --- fail closed (SAN-001.D2) ----------------------------------------------------------------


def test_a_residual_tag_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = seeded(tmp_path, "jpg")
    monkeypatch.setattr(exif, "_write", lambda args, file: None)  # the strip does nothing
    with pytest.raises(MetadataStripError) as caught:
        strip_metadata(path, rules())
    error = caught.value
    assert error.reason == RESIDUAL_REASON == "sanitize_metadata_residual"
    assert error.__cause__ is None and error.__context__ is None
    assert_clean(str(error))
    assert "Artist" not in str(error) and "GPS" not in str(error)


def test_a_failing_exiftool_fails_closed_without_its_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = seeded(tmp_path, "jpg")
    leak = SECRETS["Artist"].encode()
    real = exif._exiftool

    def failing(args: list[str]) -> subprocess.CompletedProcess[bytes] | None:
        if "-overwrite_original" in args:
            return subprocess.CompletedProcess(args, 1, stdout=leak, stderr=leak)
        return real(args)

    monkeypatch.setattr(exif, "_exiftool", failing)
    with pytest.raises(MetadataStripError) as caught:
        strip_metadata(path, rules())
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert_clean(str(caught.value) + repr(caught.value))


@pytest.mark.parametrize("trouble", ["missing", "timeout"])
def test_a_missing_or_hung_exiftool_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, trouble: str
) -> None:
    path = make_image(tmp_path / "work.jpg", "JPEG")

    def run(*args: object, **kwargs: object) -> object:
        if trouble == "missing":
            raise FileNotFoundError(2, "no such file", SECRETS["Artist"])
        raise subprocess.TimeoutExpired(cmd=[SECRETS["Artist"]], timeout=1)

    monkeypatch.setattr(exif.subprocess, "run", run)
    with pytest.raises(MetadataStripError) as caught:
        strip_metadata(path, rules())
    assert caught.value.__cause__ is None and caught.value.__context__ is None
    assert_clean(str(caught.value))


def test_a_missing_working_copy_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(MetadataStripError) as caught:
        strip_metadata(tmp_path / "absent.jpg", rules())
    assert caught.value.__context__ is None


# --- arguments and privacy ------------------------------------------------------------------


def test_option_like_values_and_paths_never_become_exiftool_options(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    path = make_image(tmp_path / "-ver", "JPEG")  # a relative `-ver` would print a version
    seed(path, f"-Artist={OPTION_LIKE}", "-XMP-dc:Creator=-all=", "-Comment=-@ /etc/passwd")
    original = pixels(path)
    calls = spy_on_exiftool(monkeypatch)

    redactions = strip_metadata(Path("-ver"), rules())

    assert not {"Artist", "Creator", "Comment"} & names(read_tags(path))
    assert pixels(path) == original
    assert before_hash(OPTION_LIKE, KEY) in {row.before_hash for row in redactions}
    for args in calls:
        if args != ["-list"]:
            assert args[-1].startswith("/")  # the path is absolute, never an option
        assert not any(OPTION_LIKE in arg or "/etc/passwd" in arg for arg in args)


def test_planted_secrets_appear_nowhere(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    keyword = "ZyxwqPlonkKeyword"
    path = tmp_path / "work.png"
    info = PngImagePlugin.PngInfo()
    info.add_text(keyword, SECRETS["Comment"])
    picture().save(path, "PNG", pnginfo=info, icc_profile=SRGB)
    seed(path)
    tags = read_tags(path)
    assert keyword in names(tags)

    redactions = strip_metadata(path, rules())

    assert "exif:PNG:unknown" in {row.field for row in redactions}  # SAN-001.D14
    text = surfaces(tags, *tags.entries, redactions, *redactions, *(r.field for r in redactions))
    assert_clean(text)
    assert keyword not in text
    assert all(DB_FIELD_CHECK.fullmatch(row.field) for row in redactions)

    # And through the failure path: the residual's message names neither.
    info = PngImagePlugin.PngInfo()
    info.add_text(keyword, SECRETS["Comment"])
    picture().save(path, "PNG", pnginfo=info, icc_profile=SRGB)
    seed(path)
    monkeypatch.setattr(exif, "_write", lambda args, file: None)
    with pytest.raises(MetadataStripError) as caught:
        strip_metadata(path, rules())
    assert_clean(str(caught.value) + repr(caught.value))
    assert keyword not in str(caught.value) + repr(caught.value)
    assert_clean(caplog.text)
    assert keyword not in caplog.text


def test_a_value_with_a_lone_surrogate_is_hashed_not_refused() -> None:
    # exiftool's output is decoded with surrogateescape, so a byte that isn't UTF-8
    # arrives as a lone surrogate; before_hash takes it with surrogatepass.
    value = b"Zyxwq\xff".decode("utf-8", "surrogateescape")
    tag = Tag("EXIF", "IFD0", "Artist", value)
    rows = exif._redactions(Tags("JPEG", (tag,)), Tags("JPEG", ()), rules())
    assert [row.field for row in rows] == ["exif:EXIF:Artist"]
    assert rows[0].before_hash == before_hash(value, KEY)


def test_working_copy_with_spaces_and_non_ascii_name(tmp_path: Path) -> None:
    folder = tmp_path / "dossier été"
    folder.mkdir()
    path = seeded(tmp_path, "webp")
    target = Path(shutil.move(path, folder / "copie çà.webp"))
    strip_metadata(target, rules())
    assert not NEVER_SURVIVES & names(read_tags(target))
