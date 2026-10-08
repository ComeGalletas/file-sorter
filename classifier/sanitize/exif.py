"""Lossless metadata strip and read-back through exiftool (R-SAN-2, R-SAN-6, SAN-001.D3).

Runs on a working copy only (FOP-001: `partial(strip_metadata, rules=rules)` is its
transform). exiftool is called with fixed argument lists, never through a shell, and the
path is made absolute so it can't be read as an option. No tag value is ever put in an
argument.

Privacy: tag values are private, and so are tag and group names read from a file (a PNG
text keyword or an XMP namespace is free text). No value or name read from a file
appears in a repr, an exception or a log; exiftool's own output never reaches a message,
and every error is raised outside its `except` block. Only `sanitize_log` fields carry a
name, and only one exiftool itself knows (SAN-001.D14).
"""

import functools
import json
import re
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from classifier.sanitize.rules import ExifFieldRule, Redaction, Rules, before_hash

EXIFTOOL = "exiftool"
TIMEOUT_SECONDS = 120  # per exiftool call (SAN-001.2 plan, approved on #48)

STRIP_ALL_RULE_ID = "exif-strip-all"  # SAN-001.D12: rows for tags the keep-list strip removed
FIELD_PREFIX = "exif:"  # DB-002.D1
UNKNOWN_TAG = "unknown"  # SAN-001.D14: a tag name exiftool doesn't know may be free text

RESIDUAL_REASON = "sanitize_metadata_residual"  # SAN-001.D2

_READ_ARGS = ("-j", "-G0:1", "-a", "-u", "-n", "-e", "-b")
_WRITE_ARGS = ("-m", "-q", "-q", "-overwrite_original")
# SAN-001.D4 and D13: the ICC profile and the Adobe APP14 segment decide how the pixels
# render, so `-all=` leaves them alone.
_STRIP_ARGS = ("-all=", "--ICC_Profile:all", "--Adobe:all")

_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")
_FIELD = re.compile(r"exif:[A-Za-z][A-Za-z0-9_:-]{0,63}")  # DB-002.D1's check

# Read, but never metadata: file-system facts and exiftool's own version and warnings.
_SKIPPED_GROUPS = frozenset({"System", "ExifTool"})

# Groups kept whole: SAN-001.D4 (ICC, family 0) and D13 (Adobe APP14, family 1).
_STRUCTURE_GROUP0 = frozenset({"ICC_Profile"})
_STRUCTURE_GROUP1 = frozenset({"Adobe"})

# File-structure tags (R-SAN-2: dimensions, encoding), by family-1 group. Also the EXIF
# and XMP containers exiftool itself recreates to hold the keep list.
_STRUCTURE_TAGS: dict[str, frozenset[str]] = {
    group: frozenset(tags.split())
    for group, tags in {
        "File": """
            FileType FileTypeExtension MIMEType ExifByteOrder ImageWidth ImageHeight
            EncodingProcess BitsPerSample ColorComponents YCbCrSubSampling
            BMPVersion Planes BitDepth Compression ImageLength PixelsPerMeterX
            PixelsPerMeterY NumColors NumImportantColors RedMask GreenMask BlueMask
            AlphaMask ColorSpace RedEndpoint GreenEndpoint BlueEndpoint GammaRed
            GammaGreen GammaBlue RenderingIntent ProfileDataOffset ProfileSize
        """,
        "IFD0": """
            ImageWidth ImageHeight BitsPerSample Compression PhotometricInterpretation
            StripOffsets SamplesPerPixel RowsPerStrip StripByteCounts
            PlanarConfiguration Predictor TileWidth TileLength TileOffsets
            TileByteCounts ExtraSamples SampleFormat ColorMap FillOrder SubfileType
            XResolution YResolution ResolutionUnit YCbCrSubSampling YCbCrPositioning
            YCbCrCoefficients ReferenceBlackWhite InkSet
        """,
        "ExifIFD": "ExifVersion ComponentsConfiguration ColorSpace",
        "XMP-x": "XMPToolkit",
        "PNG": """
            ImageWidth ImageHeight BitDepth ColorType Compression Filter Interlace
            ProfileName Gamma SRGBRendering WhitePointX WhitePointY RedX RedY GreenX
            GreenY BlueX BlueY Palette Transparency BackgroundColor SignificantBits
            PixelsPerUnitX PixelsPerUnitY PixelUnits AnimationFrames AnimationPlays
        """,
        "RIFF": """
            ImageWidth ImageHeight AlphaIsUsed WebP_Flags VP8Version HorizontalScale
            VerticalScale AnimationLoopCount BackgroundColor
        """,
        "GIF": """
            GIFVersion ImageWidth ImageHeight HasColorMap ColorResolutionDepth
            BitsPerPixel BackgroundColor AnimationIterations FrameCount Duration
            TransparentColor
        """,
        "QuickTime": """
            MajorBrand MinorVersion CompatibleBrands HandlerType ImageSpatialExtent
            ImagePixelDepth MediaData MediaDataOffset MediaDataSize
            HEVCConfigurationVersion GeneralProfileSpace GeneralTierFlag
            GeneralProfileIDC GenProfileCompatibilityFlags ConstraintIndicatorFlags
            GeneralLevelIDC MinSpatialSegmentationIDC ParallelismType ChromaFormat
            BitDepthLuma BitDepthChroma AverageFrameRate ConstantFrameRate
            NumTemporalLayers TemporalIDNested CleanAperture Rotation ImageRotation
            AuxiliaryImageType PixelAspectRatio ColorProfiles ColorPrimaries
            TransferCharacteristics MatrixCoefficients VideoFullRangeFlag
        """,
        "Meta": "PrimaryItemReference",
    }.items()
}


class MetadataStripError(Exception):
    """The strip could not be done or proven: the file fails closed (SAN-001.D2).

    The message is fixed text: never a tag value, a tag name read from the file, or
    exiftool's own output.
    """

    reason = RESIDUAL_REASON


@dataclass(frozen=True)
class Tag:
    """One tag as exiftool reads it. Nothing shows in repr: names can be free text too."""

    group0: str = field(repr=False)
    group1: str = field(repr=False)
    name: str = field(repr=False)
    value: str = field(repr=False)

    def matches(self, entry: str) -> bool:
        """`entry` is a keep-list or `exif_field` tag: a bare name or `<group>:<name>`."""
        return entry in (self.name, f"{self.group1}:{self.name}", f"{self.group0}:{self.name}")


@dataclass(frozen=True)
class Tags:
    """A file's tags. Its repr shows the file type and the count only."""

    file_type: str
    entries: tuple[Tag, ...] = field(repr=False)

    def __repr__(self) -> str:
        return f"Tags(file_type={self.file_type!r}, count={len(self.entries)})"


def _exiftool(args: list[str]) -> subprocess.CompletedProcess[bytes] | None:
    """Run exiftool with a fixed argument list. None when it is missing or times out."""
    try:
        return subprocess.run(
            [EXIFTOOL, *args],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _absolute(path: str | Path) -> Path:
    """The working copy as an absolute path: exiftool can never take it for an option.

    A symlink is refused: FOP-001 only ever makes regular files. Every error is raised
    after its `except` block, from fixed text: an OSError's message holds the path.
    """
    problem = None
    resolved = None
    try:
        given = Path(path)
        if given.is_symlink():
            problem = "metadata strip: the working copy is a symbolic link"
        else:
            resolved = given.resolve(strict=True)
            if not resolved.is_file():
                problem = "metadata strip: the working copy is not a regular file"
    except FileNotFoundError:
        problem = "metadata strip: the working copy does not exist"
    except (OSError, RuntimeError, ValueError):  # RuntimeError: a link loop; ValueError: NUL
        problem = "metadata strip: the working copy can't be opened"
    if problem is not None or resolved is None:
        raise MetadataStripError(problem or "metadata strip: the working copy can't be opened")
    return resolved


def _as_text(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _parse(stdout: bytes) -> list[tuple[str, object]] | None:
    # surrogateescape: a value that isn't UTF-8 must not stop the read, and before_hash
    # encodes it back with surrogatepass.
    try:
        documents = json.loads(stdout.decode("utf-8", "surrogateescape"), object_pairs_hook=list)
        pairs = documents[0]
    except (ValueError, IndexError, TypeError):
        return None
    return pairs if isinstance(pairs, list) else None


def _tags(pairs: list[tuple[str, object]]) -> Tags | None:
    """Build `Tags` from exiftool's `-G0:1` keys. None for anything it can't account for.

    Every key but `SourceFile` must be `<group>:<tag>` or `<group0>:<group1>:<tag>`: a
    key of any other shape fails the read closed, so no tag escapes the read-back check.
    So does an `ExifTool:Error`, or a read with no `File:FileType`.
    """
    entries = []
    file_type = ""
    for key, value in pairs:
        if key == "SourceFile":
            continue
        parts = key.split(":")
        if len(parts) == 2:
            group0, name = parts
            group1 = group0
        elif len(parts) == 3:
            group0, group1, name = parts
        else:
            return None
        if not (group0 and group1 and name):
            return None
        if group0 == "ExifTool" and name == "Error":
            return None
        if group0 in _SKIPPED_GROUPS or group1 in _SKIPPED_GROUPS:
            continue
        if group1 == "File" and name == "FileType":
            file_type = _as_text(value)
        entries.append(Tag(group0, group1, name, _as_text(value)))
    if not file_type:  # exiftool always names the type of a file it read: `[{}]` is no read
        return None
    return Tags(file_type, tuple(entries))


def read_tags(path: str | Path) -> Tags:
    """Every tag exiftool reads from `path`, except file-system facts and composites."""
    file = _absolute(path)
    done = _exiftool([*_READ_ARGS, str(file)])
    pairs = _parse(done.stdout) if done is not None and done.returncode == 0 else None
    tags = None
    if pairs is not None:
        # Raised after the except block: unexpected JSON (a non-pair, a non-string key, a
        # value json can't dump) must fail closed without chaining the original error.
        try:
            tags = _tags(pairs)
        except (ValueError, TypeError, AttributeError):
            tags = None
    if tags is None:
        raise MetadataStripError("metadata read-back: exiftool's output could not be accounted for")
    return tags


@functools.cache
def _known_tags() -> frozenset[str]:
    """Every tag name exiftool knows (`exiftool -list`), read once per process."""
    done = _exiftool(["-list"])
    if done is None or done.returncode != 0:
        raise MetadataStripError("metadata strip: exiftool could not list its tag names")
    return _tag_names(done.stdout.decode("ascii", "replace"))


def _tag_names(listing: str) -> frozenset[str]:
    """The indented name lines under `Available tags:` only: neither a section header's
    words nor the `Command-line shortcuts:` section count as tag names."""
    names: set[str] = set()
    in_tags = False
    for line in listing.splitlines():
        if not line.strip():
            continue
        if not line[:1].isspace():
            in_tags = line.strip() == "Available tags:"
            continue
        if in_tags:
            names.update(word for word in line.split() if _NAME.fullmatch(word))
    return frozenset(names)


def log_field(tag: Tag) -> str:
    """`exif:<group0>:<tag>`, or `exif:<group0>:unknown` (SAN-001.D14, DB-002.D1)."""
    if not _NAME.fullmatch(tag.group0):
        return FIELD_PREFIX + UNKNOWN_TAG
    candidate = f"{FIELD_PREFIX}{tag.group0}:{tag.name}"
    if tag.name in _known_tags() and _FIELD.fullmatch(candidate):
        return candidate
    return f"{FIELD_PREFIX}{tag.group0}:{UNKNOWN_TAG}"


def _is_structure(tag: Tag) -> bool:
    if tag.group0 in _STRUCTURE_GROUP0 or tag.group1 in _STRUCTURE_GROUP1:
        return True
    return tag.name in _STRUCTURE_TAGS.get(tag.group1, frozenset())


def is_structure_tag(tag: Tag) -> bool:
    """True for a file-structure tag the strip always keeps (R-SAN-2, SAN-001.D4, D13, D15).

    The ICC profile, Adobe APP14, and the dimension and encoding tags of each format. It is
    the strip's own allow-list, public so gate 2 (#58) can judge outputs with it.
    """
    return _is_structure(tag)


def _drop_rule(tag: Tag, rules: Rules) -> str | None:
    for rule in rules.of_type(ExifFieldRule):
        if any(tag.matches(entry) for entry in rule.fields):
            return rule.id
    return None


def is_allowed(tag: Tag, rules: Rules) -> bool:
    """True if `tag` may stay after the strip: structure, or kept and not dropped (D3, D15).

    The read-back check's own judgement, public for gate 2 (#58).
    """
    return _allowed(tag, rules)


def _allowed(tag: Tag, rules: Rules) -> bool:
    # SAN-001.D15: an exif_field rule beats the keep list, never the structure tags.
    if _is_structure(tag):
        return True
    if _drop_rule(tag, rules) is not None:
        return False
    return any(tag.matches(entry) for entry in rules.exif.keep)


def _write(args: list[str], file: Path) -> None:
    done = _exiftool([*_WRITE_ARGS, *args, str(file)])
    if done is None or done.returncode != 0:
        raise MetadataStripError("metadata strip: exiftool could not rewrite the file")


def _strip_all(file: Path, rules: Rules) -> None:
    dropped = {entry for rule in rules.of_type(ExifFieldRule) for entry in rule.fields}
    copied = [f"-{entry}" for entry in rules.exif.keep if entry not in dropped]
    # Keep entries are TagName-validated at load, so none can carry `=` or a value.
    _write([*_STRIP_ARGS, *(["-tagsFromFile", "@", *copied] if copied else [])], file)


def _delete_leftovers(leftovers: list[Tag], file: Path) -> bool:
    """Delete each tag `-all=` left (TIFF keeps IFD0). False if one can't be named safely."""
    args = []
    for tag in leftovers:
        if not (_NAME.fullmatch(tag.group1) and _NAME.fullmatch(tag.name)):
            return False
        args.append(f"-{tag.group1}:{tag.name}=")
    _write(sorted(set(args)), file)
    return True


def _redactions(before: Tags, after: Tags, rules: Rules) -> list[Redaction]:
    """One row per tag value present before and gone after (SAN-001.D3, D12)."""
    remaining = Counter(after.entries)
    rows = []
    for tag in before.entries:
        if remaining[tag] > 0:
            remaining[tag] -= 1
            continue
        rule_id = _drop_rule(tag, rules) or STRIP_ALL_RULE_ID
        rows.append(Redaction(rule_id, log_field(tag), before_hash(tag.value, rules.log_key), None))
    return rows


def strip_metadata(path: str | Path, rules: Rules) -> list[Redaction]:
    """Strip every tag outside the keep list from the working copy at `path`, losslessly.

    The keep list (`rules.exif.keep`) is copied back unless an `exif_field` rule names the
    tag. The ICC profile, Adobe APP14 and file-structure tags stay. A read-back must show
    nothing else, or `MetadataStripError` is raised (SAN-001.D2, D3). BMP can't be
    written by exiftool and carries no metadata block, so it is only read back.
    Returns one `Redaction` per removed tag value.
    """
    file = _absolute(path)
    before = read_tags(file)
    if before.file_type != "BMP":
        _strip_all(file, rules)
    after = read_tags(file)
    leftovers = [tag for tag in after.entries if not _allowed(tag, rules)]
    if leftovers and before.file_type != "BMP":
        if _delete_leftovers(leftovers, file):
            after = read_tags(file)
            leftovers = [tag for tag in after.entries if not _allowed(tag, rules)]
    if leftovers:
        raise MetadataStripError(
            f"metadata read-back: {len(leftovers)} tag(s) left outside the keep list"
        )
    return _redactions(before, after, rules)
