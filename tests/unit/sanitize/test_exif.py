"""SAN-001.2: lossless metadata strip and read-back (SAN-001.D3, D4, D11–D15).

Synthetic images only, generated here and seeded with made-up tag values through exiftool.
"""

import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image, ImageCms
from pillow_heif import register_heif_opener

from classifier.sanitize import exif
from classifier.sanitize.exif import (
    MetadataStripError,
    Tag,
    Tags,
    log_field,
    read_tags,
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
# DB-002.D1's check constraint on sanitize_log.field: SAN-001.D14 must fit it.
DB_FIELD_CHECK = re.compile(r"^exif:[A-Za-z][A-Za-z0-9_:-]{0,63}$")

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


def test_a_value_with_a_lone_surrogate_is_hashed_not_refused() -> None:
    # exiftool's output is decoded with surrogateescape, so a byte that isn't UTF-8
    # arrives as a lone surrogate; before_hash takes it with surrogatepass.
    value = b"Zyxwq\xff".decode("utf-8", "surrogateescape")
    tag = Tag("EXIF", "IFD0", "Artist", value)
    rows = exif._redactions(Tags("JPEG", (tag,)), Tags("JPEG", ()), rules())
    assert [row.field for row in rows] == ["exif:EXIF:Artist"]
    assert rows[0].before_hash == before_hash(value, KEY)
