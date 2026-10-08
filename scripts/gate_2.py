"""Milestone 2 gate: Sanitize (DESIGN.md §11).

Criterion: 50 seeded names come out with 0 residual sensitive values; EXIF on outputs contains
only the allow-list.

Runs inside the `test` container (`make gate-2`), in two halves:
  - names (TST-005.D2, D4, D6, D8): 50 seeds, drawn with a pinned seed at shares fixed below,
    from the local sanitize.yaml's `literal` values (with replacement), synthetic emails and
    phone numbers, and the fictional names in eval/data/entity_synthetic.yaml. Each seed goes
    into a relative path, which goes through `sanitize_name` with the real entity rule on live
    Ollama. No file is ever named with a seed. A seed whose value survives is a residue: 0% is
    required.
QA owns this file. Output is PASS or FAIL and percentages only: never a count, a pool size, a
per-source split, a name or a value (DOC-005.D1, TST-005.D4). Every error is fixed text.
"""

import random
import re
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

REPO = Path(__file__).resolve().parents[1]
IMAGES = REPO / "fixtures" / "images"
CONFIG = REPO / "config.yaml"
ENTITY_DATA = REPO / "eval" / "data" / "entity_synthetic.yaml"

CRITERION = (
    "50 seeded names come out with 0 residual sensitive values; EXIF on outputs contains "
    "only the allow-list."
)


class GateSetupError(Exception):
    """A prerequisite is missing; the gate fails and names it. It is never skipped.

    The message is always fixed text: never a value from sanitize.yaml or a fixture.
    """


# --- Names: the seed draw (TST-005.D2, D4, D8) -------------------------------------------

SEED = 20261007  # pinned: the same 50 seeds on every run with the same rules

# TST-005.D8: the shares are fixed here and never derived from the local pool.
LITERAL_SEEDS = 20
EMAIL_SEEDS = 5
PHONE_SEEDS = 5
PERSON_SEEDS = 10
ORG_SEEDS = 5
PLACE_SEEDS = 5
TOTAL_SEEDS = 50
assert LITERAL_SEEDS + EMAIL_SEEDS + PHONE_SEEDS + PERSON_SEEDS + ORG_SEEDS + PLACE_SEEDS == 50

LITERAL = "literal"
CONTACT = "contact"
ENTITY = "entity"
ENTITY_LABELS = ("PERSON", "ORG", "LOCATION")

SEPARATORS = " _-."  # SAN-001.D1: interchangeable inside a literal value
CASES = ("as-is", "lower", "upper", "title")
WORD_MIN = 3  # TST-005.D8: a person's first or last name word of 3+ letters is a residue too

# File-name shapes; `{v}` is the seed. Every 4th seed of a source is a folder segment.
TEMPLATES = (
    "{v}",
    "{v}_{date}_{n}",
    "IMG_{date}_{n} {v}",
    "{v} {year}",
    "trip {year} - {v}",
    "{v}-{n}",
)
FOLDER_EVERY = 4
_LETTERS = "abcdefghijklmnopqrstuvwxyz"


@dataclass(frozen=True)
class Seed:
    """One seeded name. Its repr shows the source only: the value may be the human's."""

    source: str
    value: str = field(repr=False)
    path: str = field(repr=False)  # the source-relative path fed to `sanitize_name`
    label: str = ""  # PERSON, ORG or LOCATION for an entity seed
    words: tuple[str, ...] = field(default=(), repr=False)  # TST-005.D8, person seeds only


@dataclass(frozen=True)
class EntityNames:
    """The fictional names of eval/data/entity_synthetic.yaml (MOD-001.2)."""

    first: tuple[str, ...]
    last: tuple[str, ...]
    orgs: tuple[str, ...]
    places: tuple[str, ...]
    separators: tuple[str, ...]


def entity_names(data: object) -> EntityNames:
    """Parse entity_synthetic.yaml's data, or raise naming the file (it is committed)."""
    problem = "eval/data/entity_synthetic.yaml is not in the expected shape (MOD-001.2)"
    if not isinstance(data, Mapping) or not isinstance(data.get("people"), Mapping):
        raise GateSetupError(problem)
    people = data["people"]
    lists = (
        people.get("first"),
        people.get("last"),
        data.get("orgs"),
        data.get("places"),
        data.get("separators"),
    )
    for values in lists:
        if not isinstance(values, list) or not all(isinstance(v, str) for v in values):
            raise GateSetupError(problem)
    if not all(lists[:4]) or not lists[4]:
        raise GateSetupError(problem)
    return EntityNames(*(tuple(values) for values in lists))  # type: ignore[arg-type]


def literal_values(rules: Iterable[object]) -> list[str]:
    """Every value of every `literal` rule, in file order."""
    return [
        value
        for rule in rules
        if getattr(rule, "type", None) == LITERAL
        for value in getattr(rule, "values", ())
    ]


def replacement_tokens(rules: Iterable[object]) -> tuple[str, ...]:
    """The text each rule writes in place of a match. A token is not a residue, even when a
    seeded value happens to be spelled like it (a literal `person` and `[PERSON]`)."""
    tokens: set[str] = set()
    for rule in rules:
        replace = getattr(rule, "replace", None)
        if not isinstance(replace, str) or not replace:
            continue
        if getattr(rule, "type", None) == ENTITY:
            tokens.update(replace.format(label=label) for label in ENTITY_LABELS)
        else:
            tokens.add(replace)
    return tuple(sorted(tokens, key=len, reverse=True))


def _rng(seed: int, stream: str) -> random.Random:
    # One stream per purpose, so the literal pick (which depends on the pool size) never
    # shifts any other draw (TST-005.D4).
    return random.Random(f"gate-2:{seed}:{stream}")


def _respell(value: str, sep: str) -> str:
    return sep.join(re.split(f"[{re.escape(SEPARATORS)}]", value))


def _recase(value: str, case: str) -> str:
    changed = {
        "lower": value.lower(),
        "upper": value.upper(),
        "title": value.title(),
    }.get(case, value)
    # A case change that alters the length or the letters (`ß` -> `SS`) is no longer the
    # same value to a case-insensitive match: keep the value as written then.
    if len(changed) != len(value) or changed.casefold() != value.casefold():
        return value
    return changed


def _digits(rng: random.Random, count: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(count))


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_LETTERS) for _ in range(6))


def _place(value: str, rng: random.Random, index: int) -> str:
    template = rng.choice(TEMPLATES)
    date = f"20{rng.randrange(29, 32)}{rng.randrange(1, 13):02d}{rng.randrange(1, 29):02d}"
    n = _digits(rng, 4)
    year = str(rng.randrange(2029, 2032))
    name = template.format(v=value, date=date, n=n, year=year)
    if index % FOLDER_EVERY == FOLDER_EVERY - 1:
        return f"{name}/IMG_{date}_{n}.jpg"
    return f"{name}.jpg"


def _literal_seeds(pool: Sequence[str], seed: int) -> list[Seed]:
    pick, shape = _rng(seed, "literal-pick"), _rng(seed, "literal-shape")
    seeds = []
    for index in range(LITERAL_SEEDS):
        value = pool[pick.randrange(len(pool))]  # with replacement (TST-005.D4)
        spelled = _recase(_respell(value, shape.choice(SEPARATORS)), shape.choice(CASES))
        seeds.append(Seed(LITERAL, spelled, _place(spelled, shape, index)))
    return seeds


def _contact_seeds(seed: int) -> list[Seed]:
    rng = _rng(seed, CONTACT)
    seeds = []
    for index in range(EMAIL_SEEDS):
        a, b, c = _word(rng), _word(rng), _word(rng)
        value = (
            f"{a}.{b}@{c}.invalid",
            f"{a}{_digits(rng, 2)}@{c}-{b}.test",
            f"{a}+{b}@{c}.example",
        )[index % 3]
        seeds.append(Seed(CONTACT, value, _place(value, rng, index)))
    for index in range(PHONE_SEEDS):
        cc = rng.choice(("1", "33", "44", "49", "57"))
        d3, e3, d4 = _digits(rng, 3), _digits(rng, 3), _digits(rng, 4)
        value = (
            f"+{cc} {d3} {e3} {d4}",
            f"({d3}) {e3}-{d4}",
            f"{d3}.{e3}.{d4}",
            f"+{cc}-{d3}-{e3}-{d4}",
            f"0{d3}{e3}{d4}",
        )[index % 5]
        seeds.append(Seed(CONTACT, value, _place(value, rng, EMAIL_SEEDS + index)))
    return seeds


def _entity_seeds(names: EntityNames, seed: int) -> list[Seed]:
    seeds = []
    rng = _rng(seed, "person")
    for index in range(PERSON_SEEDS):
        first, last = rng.choice(names.first), rng.choice(names.last)
        value = f"{first}{rng.choice(names.separators)}{last}"
        words = tuple(w for w in (first, last) if sum(c.isalpha() for c in w) >= WORD_MIN)
        seeds.append(Seed(ENTITY, value, _place(value, rng, index), "PERSON", words))
    for stream, count, pool, label in (
        ("org", ORG_SEEDS, names.orgs, "ORG"),
        ("place", PLACE_SEEDS, names.places, "LOCATION"),
    ):
        rng = _rng(seed, stream)
        for index in range(count):
            value = _respell(rng.choice(pool), rng.choice(names.separators))
            seeds.append(Seed(ENTITY, value, _place(value, rng, index), label))
    return seeds


def draw_seeds(literals: Sequence[str], names: EntityNames, seed: int = SEED) -> tuple[Seed, ...]:
    """The gate's 50 seeds, in a fixed order: literal, contact, entity."""
    if not literals:
        raise GateSetupError(
            "sanitize.yaml has no `literal` rule: gate 2 seeds the human's own values from it "
            "(TST-005.D2). Add one (see sanitize.example.yaml, make init)."
        )
    return (
        *_literal_seeds(literals, seed),
        *_contact_seeds(seed),
        *_entity_seeds(names, seed),
    )


# --- Names: the residual check (TST-005.D2, D8) ------------------------------------------

_SPLIT = re.compile(f"[{re.escape(SEPARATORS)}]+")
_GAP = f"[{re.escape(SEPARATORS)}]*"  # stricter than SAN-001.D1: a separator may also be gone


def _pattern(value: str) -> re.Pattern[str] | None:
    parts = [part for part in _SPLIT.split(value) if part]
    if not parts:
        return None
    return re.compile(_GAP.join(re.escape(part) for part in parts), re.IGNORECASE)


def has_residue(seed: Seed, sanitized: str, tokens: Sequence[str] = ()) -> bool:
    """True when `seed`'s value (or, for a person, a name word) survives in `sanitized`.

    The gate's own matcher, not the rules' (a bug there can't hide itself here). Each
    separator matches any of SAN-001.D1's four or none, case-insensitively. Replacement
    tokens are masked first.
    """
    for token in tokens:
        sanitized = sanitized.replace(token, "\x00")
    for probe in (seed.value, *seed.words):
        pattern = _pattern(probe)
        if pattern is not None and pattern.search(sanitized):
            return True
    return False


def _tenths(tenths: int) -> str:
    return f"{tenths // 10}.{tenths % 10}%"


def _pct_up(part: int, whole: int) -> str:
    """A share rounded up, in integers, so a residue never prints as 0.0%."""
    return _tenths(-(-1000 * part // whole))


def _pct_down(part: int, whole: int) -> str:
    """A share rounded down, in integers, so a miss never prints as 100.0%."""
    return _tenths(1000 * part // whole)


def judge_names(residues: Sequence[bool]) -> tuple[bool, str]:
    """One line: the residual share of the seeds (0.0% required). Never a count."""
    if len(residues) != TOTAL_SEEDS:
        return False, "names: the draw did not make 50 seeds: FAIL"
    ok = not any(residues)
    share = _pct_up(sum(residues), len(residues))
    return ok, f"names: residual seeded values {share} (required 0.0%): {'ok' if ok else 'FAIL'}"


# --- Metadata: the judge (R-SAN-2; SAN-001.D3, D4, D13, D15; TST-005.D7) ---------------


class TagLike(Protocol):
    """`classifier.sanitize.exif.Tag`, as the judge uses it."""

    def matches(self, entry: str) -> bool: ...


def tag_allowed(
    tag: TagLike,
    keep: Sequence[str],
    dropped: Sequence[str],
    is_structure: Callable[[Any], bool],
) -> bool:
    """A tag may stay when it is a file-structure, ICC or Adobe APP14 tag (`is_structure`,
    from exif.py), or in the keep list and not named by an `exif_field` rule (D15)."""
    if is_structure(tag):
        return True
    if any(tag.matches(entry) for entry in dropped):
        return False
    return any(tag.matches(entry) for entry in keep)


def output_clean(
    entries: Iterable[TagLike],
    keep: Sequence[str],
    dropped: Sequence[str],
    is_structure: Callable[[Any], bool],
) -> bool:
    return all(tag_allowed(tag, keep, dropped, is_structure) for tag in entries)


def carries_marker(data: bytes, markers: Iterable[str]) -> bool:
    """True when any seeded metadata marker is in `data`, in UTF-8 or UTF-16 (either order).

    Independent of the tag read: a value that exiftool lists under a structure tag, or
    doesn't list at all, still fails here.
    """
    return any(
        marker.encode(encoding) in data
        for marker in markers
        for encoding in ("utf-8", "utf-16-le", "utf-16-be")
    )


def judge_metadata(name: str, inputs: int, sanitized: int, clean: int) -> tuple[bool, str]:
    """One line per set: the share of inputs the node sanitized (TST-005.D7) and the share
    of outputs that are clean, both 100.0% required. Never a count."""
    if inputs == 0:
        return False, f"metadata, {name}: nothing reached the sanitize node: FAIL"
    ok = sanitized == inputs and clean == sanitized
    clean_share = _pct_down(clean, sanitized) if sanitized else "0.0%"
    return ok, (
        f"metadata, {name}: {_pct_down(sanitized, inputs)} sanitized, {clean_share} of outputs "
        f"clean (required 100.0% and 100.0%): {'ok' if ok else 'FAIL'}"
    )


# --- Metadata: the synthetic set ---------------------------------------------------------

# (extension, Pillow format, mode). The CMYK JPEG carries Adobe APP14 (SAN-001.D13); every
# format that takes one carries an sRGB ICC profile (SAN-001.D4).
SYNTHETIC_FORMATS = (
    ("jpg", "JPEG", "RGB"),
    ("jpg", "JPEG", "CMYK"),
    ("png", "PNG", "RGB"),
    ("tif", "TIFF", "RGB"),
    ("webp", "WEBP", "RGB"),
    ("heic", "HEIF", "RGB"),
    ("gif", "GIF", "P"),
)
# Text tags seeded with a marker each: EXIF, XMP, IPTC and file comments.
MARKED_TAGS = (
    "EXIF:Artist",
    "EXIF:Copyright",
    "EXIF:ImageDescription",
    "EXIF:Make",
    "EXIF:Model",
    "EXIF:Software",
    "EXIF:UserComment",
    "EXIF:SerialNumber",
    "XMP-dc:Creator",
    "XMP-dc:Description",
    "XMP-dc:Subject",
    "XMP-photoshop:City",
    "IPTC:By-line",
    "IPTC:Caption-Abstract",
    "IPTC:Keywords",
    "IPTC:City",
    "Comment",
)
GPS_SEED = ("-GPSLatitude=12.3456", "-GPSLatitudeRef=N", "-GPSLongitude=65.4321",
            "-GPSLongitudeRef=W", "-GPSAltitude=123")  # fmt: skip
KEEP_SEED = ("-Orientation#=6", "-DateTimeOriginal=2031:04:05 10:15:32")
EXIFTOOL_TIMEOUT = 120


def _picture(mode: str) -> Any:
    from PIL import Image

    image = Image.new("RGB", (24, 16), (10, 200, 30))
    for x in range(24):
        image.putpixel((x, 5), (x * 10, 0, 255))
        image.putpixel((x, 9), (255, x * 10, 0))
    return image.convert(mode)


def make_seeded_images(folder: Path, seed: int = SEED) -> tuple[str, ...]:
    """Write the synthetic set into `folder` and return its markers.

    Raises `GateSetupError` when an image can't be written or seeded: a set that carries
    no metadata would pass the gate without proving anything.
    """
    import subprocess

    from PIL import ImageCms
    from pillow_heif import register_heif_opener

    register_heif_opener()
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    rng = _rng(seed, "metadata")
    markers: list[str] = []
    for index, (ext, fmt, mode) in enumerate(SYNTHETIC_FORMATS):
        path = folder / f"synthetic_{index:02d}.{ext}"
        options: dict[str, object] = {} if fmt == "GIF" else {"icc_profile": srgb}
        if fmt == "WEBP":
            options["lossless"] = True
        _picture(mode).save(path, fmt, **options)
        own = [f"G2SEED{index:02d}x{rng.getrandbits(40):010x}" for _ in MARKED_TAGS]
        args = [f"-{tag}={marker}" for tag, marker in zip(MARKED_TAGS, own, strict=True)]
        try:
            seeded = subprocess.run(
                ["exiftool", "-m", "-q", "-q", "-overwrite_original", *args, *GPS_SEED,
                 *KEEP_SEED, str(path)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=EXIFTOOL_TIMEOUT,
                check=False,
            ).returncode == 0 and carries_marker(path.read_bytes(), own)  # fmt: skip
        except (OSError, subprocess.TimeoutExpired):  # raised below, unchained
            seeded = False
        if not seeded:
            raise GateSetupError(
                "the synthetic images could not be seeded with metadata: check exiftool "
                "in the test image (make build)"
            )
        markers.extend(own)
    return tuple(markers)


def main() -> int:
    print(f"gate 2 NOT IMPLEMENTED: {CRITERION}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
