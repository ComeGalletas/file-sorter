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
  - metadata (R-SAN-2; SAN-001.D3, D4, D13; TST-005.D6, D7): ingest and the sanitize node run
    end to end, in a fresh schema and a removed temp results tree, over a synthetic set seeded
    with EXIF, XMP, IPTC, GPS and comment markers, then over fixtures/images/. Every queued
    input must reach `sanitized`, and every working copy may carry only keep-list, structure,
    ICC and Adobe APP14 tags. No synthetic marker may remain in any results file.
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

# `python scripts/gate_2.py` puts scripts/, not the repo, on sys.path; the lazy imports of
# `classifier` and `tests` below need the repo.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

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


def judge_metadata(
    name: str, inputs: int, sanitized: int, clean: int, shares: bool = True
) -> tuple[bool, str]:
    """One line per set: the share of inputs the node sanitized (TST-005.D7) and the share
    of outputs that are clean, both 100.0% required. Never a count.

    `shares=False` prints the verdict only: on a small real set, a share below 100% would
    reveal the set's size (85.7% is 6 of 7; PR #84's privacy audit).
    """
    if inputs == 0:
        return False, f"metadata, {name}: nothing reached the sanitize node: FAIL"
    ok = sanitized == inputs and clean == sanitized
    if not shares:
        return ok, (
            f"metadata, {name}: every input sanitized and clean (required): "
            f"{'ok' if ok else 'FAIL'}"
        )
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


def judge_leak(leaked: bool) -> tuple[bool, str]:
    """The marker-bytes check over every file the synthetic run left in its results tree."""
    status = "FAIL" if leaked else "ok"
    return not leaked, f"metadata, synthetic: seeded values in results files: {status}"


@dataclass(frozen=True)
class Verdict:
    passed: bool
    lines: tuple[str, ...]


def verdict(*judged: tuple[bool, str]) -> Verdict:
    ok = all(passed for passed, _ in judged)
    lines = (*(line for _, line in judged), f"gate 2 {'PASS' if ok else 'FAIL'}: {CRITERION}")
    return Verdict(ok, lines)


# --- The run (inside the `test` container) ----------------------------------------------
# Every error below is raised after its `except` block, from fixed text: an exception from
# the rules, the detector or the filesystem may quote a value or a path.

PROBE_TEXT = "Zorvane Quillby at Brakmoor Works"  # fictional (entity_synthetic.yaml)
NODES = ("ingest", "sanitize")


class GateRunError(Exception):
    """A step failed while measuring; fixed text only, like `GateSetupError`."""


def gate_nodes(registry: Sequence[Any]) -> tuple[Any, ...]:
    """The ingest and sanitize nodes, in that order: the gate never runs a later node."""
    picked = tuple(node for name in NODES for node in registry if node.name == name)
    if tuple(node.name for node in picked) != NODES:
        raise GateSetupError(
            "the node registry must hold exactly one `ingest` and one `sanitize` node "
            "(SAN-001.4, #56)"
        )
    return picked


def structure_predicate() -> Callable[[Any], bool]:
    """exif.py's public structure-tag predicate (TST-005.D8), never a private one."""
    from classifier.sanitize import exif

    predicate = getattr(exif, "is_structure_tag", None)
    if not callable(predicate):
        raise GateSetupError(
            "classifier/sanitize/exif.py has no public is_structure_tag: it comes with "
            "SAN-001.4 (#56)"
        )
    return predicate


def load_entity_names(path: Path) -> EntityNames:
    import yaml

    data = None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        data = None
    if data is None:
        raise GateSetupError(
            "eval/data/entity_synthetic.yaml is missing or unreadable (MOD-001.2): gate 2 "
            "seeds its fictional names from it"
        )
    return entity_names(data)


def load_config(source: Path, results: str, dsn: str, rules_path: Path | None = None) -> Any:
    """config.yaml with the gate's roots and schema. With `rules_path`, the sanitize node
    reads the same rules file the gate judges by."""
    import yaml

    from classifier.config import Config, check_roots

    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["paths"] = {"source_root": str(source), "results_root": results}
    data["db"] = {"dsn": dsn}
    if rules_path is not None:
        data["sanitizer"] = {**data.get("sanitizer", {}), "rules_file": str(rules_path)}
    config = Config.model_validate(data)
    check_roots(config)  # R-FOP-9
    return config


def load_local_rules(path: Path) -> Any:
    """The rules file, or a fixed message: SanitizeConfigError's text is value-free, but the
    gate prints only fixed text about the human's file (TST-005.D4)."""
    import os

    from classifier.sanitize.rules import LOG_KEY_ENV, SanitizeConfigError, load_rules

    if not os.environ.get(LOG_KEY_ENV, "").strip():
        raise GateSetupError(f"{LOG_KEY_ENV} is not set: run make init, then make gate-2")
    rules = None
    try:
        rules = load_rules(path)
    except SanitizeConfigError:
        rules = None
    if rules is None:
        raise GateSetupError(
            "sanitize.yaml is missing or invalid: run make init and compare it with "
            "sanitize.example.yaml"
        )
    return rules


def probe_entity(entity: Callable[[str, Sequence[str]], Any]) -> None:
    """One call on a fictional string: Ollama is up and `models.text_llm` answers."""
    failed = False
    try:
        entity(PROBE_TEXT, ["PERSON"])
    except Exception:
        failed = True
    if failed:
        raise GateSetupError(
            "the entity rule can't reach Ollama or models.text_llm: run make models; "
            "make gate-2 starts ollama (RUN-011)"
        )


def real_entity(config: Any) -> Callable[[str, Sequence[str]], Any]:
    from classifier.models.ollama import OllamaClient
    from classifier.sanitize.entity import entity_detector

    client = None
    try:
        client = OllamaClient.from_env()
    except Exception:
        client = None
    if client is None:
        raise GateSetupError("OLLAMA_HOST is not set or invalid: run the gate with make gate-2")
    return entity_detector(config, client)


def measure_names(
    rules: Any, names: EntityNames, entity: Callable[[str, Sequence[str]], Any]
) -> tuple[bool, str]:
    """The names half (TST-005.D6): `sanitize_name` on string paths, never on files."""
    from classifier.sanitize.rules import sanitize_name

    seeds = draw_seeds(literal_values(rules.rules), names)
    tokens = replacement_tokens(rules.rules)
    residues = []
    for seed in seeds:
        sanitized = None
        try:
            name = sanitize_name(seed.path, rules, entity)
            sanitized = "/".join((*name.segments, name.stem))
        except Exception:
            sanitized = None
        if sanitized is None:
            raise GateRunError(
                "names: sanitize_name failed on a seed (the entity rule fails closed with "
                "sanitize_entity_unavailable): check Ollama and models.text_llm"
            )
        residues.append(has_residue(seed, sanitized, tokens))
    return judge_names(residues)


def _clean_output(
    work: Path,
    source_hash: str,
    rules: Any,
    is_structure: Callable[[Any], bool],
    markers: Sequence[str],
) -> bool:
    from classifier.sanitize.exif import MetadataStripError, read_tags
    from classifier.sanitize.rules import ExifFieldRule

    copies = list(work.glob(f"{source_hash}.*"))
    if len(copies) != 1:
        return False
    dropped = [entry for rule in rules.of_type(ExifFieldRule) for entry in rule.fields]
    clean = False
    try:
        entries = read_tags(copies[0]).entries
        clean = output_clean(entries, rules.exif.keep, dropped, is_structure)
        clean = clean and not carries_marker(copies[0].read_bytes(), markers)
    except (MetadataStripError, OSError):
        clean = False
    return clean


def measure_metadata(
    dsn: str,
    source: Path,
    name: str,
    rules: Any,
    rules_path: Path,
    is_structure: Callable[[Any], bool],
    nodes: Sequence[Any],
    markers: Sequence[str] = (),
    shares: bool = True,
) -> list[tuple[bool, str]]:
    """Ingest and sanitize `source` into a fresh schema and a removed temp results tree
    (TST-005.D6), then judge every input the ingest queued (TST-005.D7). The node reads
    `rules_path`, the file `rules` was loaded from. `shares=False` for the real fixtures."""
    import tempfile

    import psycopg

    from classifier.graph.run import run
    from tests.integration.schema_support import migrated_schema

    with migrated_schema(dsn) as schema, tempfile.TemporaryDirectory() as results:
        config = load_config(source, results, schema, rules_path)
        run(config, dry_run=True, nodes=tuple(nodes))
        with psycopg.connect(schema) as conn:
            rows = conn.execute(
                "select source_hash, status::text from files where status <> 'skipped'"
            ).fetchall()
        work = Path(results) / ".work"  # SAN-001.D7, FOP-001
        sanitized = [digest for digest, status in rows if status == "sanitized"]
        clean = sum(_clean_output(work, d, rules, is_structure, markers) for d in sanitized)
        judged = [judge_metadata(name, len(rows), len(sanitized), clean, shares)]
        if markers:
            leaked = any(
                carries_marker(path.read_bytes(), markers)
                for path in Path(results).rglob("*")
                if path.is_file()
            )
            judged.append(judge_leak(leaked))
    return judged


def check_prerequisites(dsn: str | None, images: Path) -> str:
    """Return the DSN, or raise naming what is missing."""
    import shutil

    if not dsn:
        raise GateSetupError(
            "DB_DSN is not set: gate 2 needs the throwaway Postgres of the `test` compose "
            "profile. Run it with `make gate-2`."
        )
    if not images.is_dir() or not any(images.iterdir()):
        raise GateSetupError(
            "fixtures/images/ is missing or empty: gate 2 sanitizes the human's real "
            "fixtures, mounted read-only into the `test` container (RUN-009). Run it with "
            "`make gate-2`."
        )
    if shutil.which("exiftool") is None:
        raise GateSetupError("exiftool is not on PATH: rebuild the test image (make build)")
    return dsn


def measure(
    dsn: str,
    images: Path,
    entity_data: Path,
    rules_path: Path | None = None,
    entity: Callable[[str, Sequence[str]], Any] | None = None,
    is_structure: Callable[[Any], bool] | None = None,
) -> Verdict:
    import tempfile

    from classifier.graph import nodes as graph_nodes

    names = load_entity_names(entity_data)
    with tempfile.TemporaryDirectory() as scratch:
        config = load_config(images, scratch, dsn)
    if rules_path is None:
        rules_path = Path(config.sanitizer.rules_file)
        rules_path = rules_path if rules_path.is_absolute() else REPO / rules_path
    rules = load_local_rules(rules_path)
    if not literal_values(rules.rules):
        draw_seeds((), names)  # raises the TST-005.D4 message before any model call
    entity = entity or real_entity(config)
    probe_entity(entity)
    nodes = gate_nodes(graph_nodes.REGISTRY)
    is_structure = is_structure or structure_predicate()

    judged = [measure_names(rules, names, entity)]
    with tempfile.TemporaryDirectory() as folder:
        markers = make_seeded_images(Path(folder))
        judged += measure_metadata(
            dsn, Path(folder), "synthetic", rules, rules_path, is_structure, nodes, markers
        )
    judged += measure_metadata(
        dsn, images, "real fixtures", rules, rules_path, is_structure, nodes, shares=False
    )
    return verdict(*judged)


def main(
    images: Path = IMAGES,
    entity_data: Path = ENTITY_DATA,
    rules_path: Path | None = None,
    entity: Callable[[str, Sequence[str]], Any] | None = None,
    is_structure: Callable[[Any], bool] | None = None,
) -> int:
    """`rules_path`, `entity` and `is_structure` are test seams; `make gate-2` passes none."""
    import os

    try:
        dsn = check_prerequisites(os.environ.get("DB_DSN"), images)
        result = measure(dsn, images, entity_data, rules_path, entity, is_structure)
    except (GateSetupError, GateRunError) as exc:  # fixed text by construction
        print(f"gate 2 FAIL: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # the type only: a message can carry a value, a path or the DSN
        print(f"gate 2 FAIL: run errored ({type(exc).__name__})", file=sys.stderr)
        return 1
    print("\n".join(result.lines))
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
