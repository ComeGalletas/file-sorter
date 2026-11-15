"""Milestone 5 gate: Name (DESIGN.md §11).

Criterion: 0 sensitive values in 500 names, which are synthetic, with seeded sensitive values
(the human's answer 4). The readability spot-check is the human's, on a real dry run, at G1.

Runs inside the `test` container (`make gate-5`), in two sections:
  - synthetic (TST-016.D1, D5): 500 rows drawn with a pinned seed at shares fixed below. Each
    row plants one seed in its synthetic source path and one in its recorded synthetic caption:
    the local sanitize.yaml's `literal` values (with replacement), coined emails and phone
    numbers, and the fictional names of eval/data/entity_synthetic.yaml. The rows go through
    the real sanitize rules, the real caption node (sanitize on write, answer 6) and the real
    name node, on the real templates. Every seed is checked against every name; one that
    survives anywhere is a residue, and none may.
  - real names (DOC-020.D2, TST-016.D2): box-only and informational. Every name in the
    git-ignored fixtures/names_local.txt goes through the sanitize rules and the
    `keep-original` and `descriptive` templates with a synthetic caption, and no `literal`
    value or `regex` match may survive. It prints one verdict line and never changes the exit
    code (TST-016.D3).
The local `literal` values are only ever held in memory: no seeded path or caption is written
to the repo, to tests/recordings/ or to a log (TST-016.1, the lead's approval).
QA owns this file. Output is fixed text, a verdict per section and the synthetic count: never a
value, a name, a caption or a count about the human's files (DOC-005.D1, TST-016.D1).
"""

import hashlib
import hmac
import importlib.util
import random
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config.yaml"
ENTITY_DATA = REPO / "eval" / "data" / "entity_synthetic.yaml"
NAMES_LOCAL = REPO / "fixtures" / "names_local.txt"

# `python scripts/gate_5.py` puts scripts/, not the repo, on sys.path.
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from classifier.naming.templates import BUILTINS, normalize  # noqa: E402


def _load_gate_2() -> Any:
    """Gate 2's committed helpers (the entity-name parser, the rule readers), loaded by path."""
    path = Path(__file__).with_name("gate_2.py")
    spec = importlib.util.spec_from_file_location("gate_2_shared", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_gate_2 = _load_gate_2()
GateSetupError = _gate_2.GateSetupError  # fixed text only; a prerequisite is missing
EntityNames = _gate_2.EntityNames
entity_names = _gate_2.entity_names
literal_values = _gate_2.literal_values
replacement_tokens = _gate_2.replacement_tokens


class GateRunError(Exception):
    """A step failed while measuring; fixed text only, like `GateSetupError`."""


CRITERION = (
    "0 sensitive values in 500 synthetic names with seeded sensitive values (answer 4); "
    "names readable without opening the file (the human's spot-check of a real dry run, at G1)."
)

# --- The draw (TST-016.D1; the shares are fixed here, never derived from the local pool) -----

SEED = 20261115  # pinned: the same 500 rows on every run with the same rules
TOTAL_NAMES = 500

LITERAL = "literal"
CONTACT = "contact"
ENTITY = "entity"

# Per 10 rows, for each of the two plants (path and caption): 4 literal, 1 email, 1 phone,
# 2 person, 1 org, 1 place.
KINDS = (
    (LITERAL, ""),
    (LITERAL, ""),
    (LITERAL, ""),
    (LITERAL, ""),
    (CONTACT, "email"),
    (CONTACT, "phone"),
    (ENTITY, "PERSON"),
    (ENTITY, "PERSON"),
    (ENTITY, "ORG"),
    (ENTITY, "LOCATION"),
)
assert TOTAL_NAMES % len(KINDS) == 0

# The six built-ins plus three gate-only user templates, so that every token that can carry
# a seed (`subject`, `detail`, `caption`, `tags`, `original_sanitized`) reaches a name.
GATE_TEMPLATES = {
    "gate-caption": "{caption}_{seq:3}",
    "gate-tags": "{tags}_{seq:3}",
    "gate-mixed": "{detail}_{original_sanitized}_{seq:3}",
}
TEMPLATE_NAMES = (*BUILTINS, *GATE_TEMPLATES)

# The caption field each template reads first: the caption seed goes there, so the seed
# reaches the name. Templates that read no caption field get a rotating field: the seed must
# still not surface anywhere.
TEMPLATE_FIELD = {
    "descriptive": "subject",
    "reference": "subject",
    "dated": "subject",
    "gate-caption": "caption",
    "gate-tags": "tags",
    "gate-mixed": "detail",
}
CAPTION_FIELDS = ("subject", "detail", "caption", "tags")

SEPARATORS = " _-."  # SAN-001.D1
CASES = ("as-is", "lower", "upper", "title")
WORD_MIN = 3  # TST-005.D8: a person's 3+-letter name word is a residue too

PATH_SHAPES = (
    "{v}",
    "{v}_{date}_{n}",
    "IMG_{date}_{n} {v}",
    "{v} {year}",
    "outing {year} - {v}",
    "{v}-{n}",
)
FOLDER_EVERY = 4
_LETTERS = "abcdefghijklmnopqrstuvwxyz"

# Coined filler for the synthetic captions (TST-005): no real word that names a thing in an
# image, no real name.
FILLER = (
    "qorvex", "zhyndel", "vruthmar", "plimbo", "ostrevan", "quillow", "drabnet", "yskel",
    "frondak", "molvine", "tazzle", "brevock", "skennow", "ulmarth", "glivven", "parrock",
)  # fmt: skip


@dataclass(frozen=True)
class Seed:
    """One planted value. Its repr shows where it was planted and its kind only."""

    kind: str
    label: str
    place: str  # "path", or the caption field
    value: str = field(repr=False)
    words: tuple[str, ...] = field(default=(), repr=False)


@dataclass(frozen=True)
class Caption:
    """A recorded synthetic caption answer, built in memory at gate time (never committed)."""

    subject: str = field(repr=False)
    detail: str = field(repr=False)
    caption: str = field(repr=False)
    tags: tuple[str, ...] = field(repr=False)


@dataclass(frozen=True)
class Row:
    """One synthetic file. Only the index, hash, template and branch show in repr."""

    index: int
    source_hash: str
    template: str
    branch: str  # "safe" | "nsfw"
    path: str = field(repr=False)  # source-relative; never a file on disk
    caption: Caption = field(repr=False)
    seeds: tuple[Seed, ...] = field(repr=False)

    @property
    def short_hash(self) -> str:
        return self.source_hash[:8]


def _rng(seed: int, stream: str) -> random.Random:
    # One stream per purpose, so the literal pick (which depends on the pool size) never
    # shifts any other draw (TST-005.D4).
    return random.Random(f"gate-5:{seed}:{stream}")


def _respell(value: str, sep: str) -> str:
    return sep.join(re.split(f"[{re.escape(SEPARATORS)}]", value))


def _recase(value: str, case: str) -> str:
    changed = {"lower": value.lower(), "upper": value.upper(), "title": value.title()}.get(
        case, value
    )
    if len(changed) != len(value) or changed.casefold() != value.casefold():
        return value  # `ß` -> `SS` is no longer the same value to a case-insensitive rule
    return changed


def _digits(rng: random.Random, count: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(count))


def _word(rng: random.Random) -> str:
    return "".join(rng.choice(_LETTERS) for _ in range(6))


def _value(
    kind: str,
    label: str,
    literals: Sequence[str],
    names: Any,
    pick: random.Random,
    rng: random.Random,
    n: int,
) -> tuple[str, tuple[str, ...]]:
    """One seed value (and, for a person, its name words). Only `pick` depends on the pool
    size, so the pool never shifts any other draw (TST-005.D4)."""
    if kind == LITERAL:
        value = literals[pick.randrange(len(literals))]  # with replacement (TST-005.D4)
        return _recase(_respell(value, rng.choice(SEPARATORS)), rng.choice(CASES)), ()
    if label == "email":
        a, b, c = _word(rng), _word(rng), _word(rng)
        return (f"{a}.{b}@{c}.invalid", f"{a}{_digits(rng, 2)}@{c}-{b}.test",
                f"{a}+{b}@{c}.example")[n % 3], ()  # fmt: skip
    if label == "phone":
        cc = rng.choice(("1", "33", "44", "49", "57"))
        d3, e3, d4 = _digits(rng, 3), _digits(rng, 3), _digits(rng, 4)
        return (f"+{cc} {d3} {e3} {d4}", f"({d3}) {e3}-{d4}", f"{d3}.{e3}.{d4}",
                f"+{cc}-{d3}-{e3}-{d4}")[n % 4], ()  # fmt: skip
    if label == "PERSON":
        first, last = rng.choice(names.first), rng.choice(names.last)
        words = tuple(w for w in (first, last) if sum(c.isalpha() for c in w) >= WORD_MIN)
        return f"{first}{rng.choice(names.separators)}{last}", words
    pool = names.orgs if label == "ORG" else names.places
    return _respell(rng.choice(pool), rng.choice(names.separators)), ()


def _path(value: str, rng: random.Random, index: int) -> str:
    shape = rng.choice(PATH_SHAPES)
    date = f"20{rng.randrange(29, 32)}{rng.randrange(1, 13):02d}{rng.randrange(1, 29):02d}"
    n = _digits(rng, 4)
    name = shape.format(v=value, date=date, n=n, year=str(rng.randrange(2029, 2032)))
    if index % FOLDER_EVERY == FOLDER_EVERY - 1:
        return f"{name}/IMG_{date}_{n}.jpg"  # the seed sits in a folder segment
    return f"{name}.png"


def _fill(rng: random.Random, count: int) -> list[str]:
    return [rng.choice(FILLER) for _ in range(count)]


def _caption(seed: Seed, rng: random.Random) -> Caption:
    a, b, c, d = _fill(rng, 4)
    fields = {
        "subject": f"{a} {b}",
        "detail": f"{c} {a} with {d}",
        "caption": f"A {b} {c} beside a {d}.",
    }
    tags = _fill(rng, 4)
    if seed.place == "tags":
        tags.insert(rng.randrange(len(tags) + 1), seed.value)
    elif seed.place == "subject":
        fields["subject"] = f"{seed.value} {a}"
    elif seed.place == "detail":
        fields["detail"] = f"{c} {seed.value} with {d}"
    else:
        fields["caption"] = f"A {b} beside {seed.value} near a {d}."
    return Caption(fields["subject"], fields["detail"], fields["caption"], tuple(tags))


def source_hash(index: int, seed: int = SEED) -> str:
    """A synthetic SHA-256 per row: no file is ever named with a seed."""
    return hashlib.sha256(f"gate-5:{seed}:row:{index}".encode()).hexdigest()


def draw_rows(literals: Sequence[str], names: Any, seed: int = SEED) -> tuple[Row, ...]:
    """The 500 rows. Pure and in memory: nothing here touches the filesystem."""
    if not literals:
        raise GateSetupError(
            "sanitize.yaml has no `literal` rule: gate 5 seeds the human's own values from it "
            "(TST-016, as TST-005.D2). Add one (see sanitize.example.yaml, make init)."
        )
    pick = {place: _rng(seed, f"{place}-literal") for place in ("path", "caption")}
    value_rng = {place: _rng(seed, f"{place}-values") for place in ("path", "caption")}
    shape, filler, where = _rng(seed, "path-shape"), _rng(seed, "filler"), _rng(seed, "field")
    rows = []
    for index in range(TOTAL_NAMES):
        template = TEMPLATE_NAMES[index % len(TEMPLATE_NAMES)]
        branch = "nsfw" if (index // len(TEMPLATE_NAMES)) % 2 else "safe"
        kind, label = KINDS[index % len(KINDS)]
        value, words = _value(kind, label, literals, names, pick["path"], value_rng["path"], index)
        in_path = Seed(kind, label, "path", value, words)
        # The caption plant uses the kind table shifted by 3, so a row's two plants differ.
        kind, label = KINDS[(index + 3) % len(KINDS)]
        value, words = _value(
            kind, label, literals, names, pick["caption"], value_rng["caption"], index
        )
        place = TEMPLATE_FIELD.get(template) or CAPTION_FIELDS[where.randrange(4)]
        in_caption = Seed(kind, label, place, value, words)
        rows.append(
            Row(
                index,
                source_hash(index, seed),
                template,
                branch,
                _path(in_path.value, shape, index),
                _caption(in_caption, filler),
                (in_path, in_caption),
            )
        )
    return tuple(rows)


def held(row: Row) -> bool:
    """Every seed of `row` is in its raw path or raw caption field: proven before absence."""
    for seed in row.seeds:
        if seed.place == "path":
            text = row.path
        elif seed.place == "tags":
            text = "\n".join(row.caption.tags)
        else:
            text = getattr(row.caption, seed.place)
        if seed.value not in text:
            return False
    return True


def check_held(rows: Iterable[Row]) -> None:
    if not all(held(row) for row in rows):
        raise GateRunError("the draw did not plant every seed it drew: the gate is broken")


# --- The residue check (TST-016.D5) -----------------------------------------------------


def probe_pattern(value: str) -> re.Pattern[str] | None:
    """The gate's own matcher on R-NAME-5-normalized text: each separator in the seed may be
    `_` or gone. None when the value normalizes to nothing (it can't be in a name then)."""
    parts = [part for part in normalize(value).split("_") if part]
    if not parts:
        return None
    return re.compile("_*".join(re.escape(part) for part in parts))


def mask_tokens(name: str, tokens: Sequence[str]) -> str:
    """Mask each rule's replacement text, in normalized form (`[PERSON]` -> `person`), where it
    stands as a whole word of the name. A token is not a residue, even when a seed is spelled
    like it; one glued into a word stays, and fails safe."""
    for token in sorted({normalize(t) for t in tokens} - {""}, key=len, reverse=True):
        name = re.sub(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", "\x00", name)
    return name


def residues(seeds: Iterable[Seed], names: Sequence[str], tokens: Sequence[str] = ()) -> list[bool]:
    """One flag per seed: True when its value, or a person's name word, is in **any** name."""
    corpus = "\n".join(mask_tokens(name, tokens) for name in names)
    flags = []
    for seed in seeds:
        patterns = [probe_pattern(probe) for probe in (seed.value, *seed.words)]
        flags.append(any(p is not None and p.search(corpus) for p in patterns))
    return flags


def judge_names(names: int, found: Sequence[bool]) -> tuple[bool, str]:
    """The public line (TST-016.D1): the synthetic count and 0 residues, or FAIL. A failing
    run prints no count of residues: `--detail` lists them on the box."""
    if names != TOTAL_NAMES:
        return False, f"names: the run did not make {TOTAL_NAMES} names: FAIL"
    head = f"names: {TOTAL_NAMES} synthetic names"
    if any(found):
        return False, f"{head}, seeded values survived (required 0): FAIL"
    return True, f"{head}, 0 residual seeded values (required 0): ok"


def seed_digest(seed: Seed, key: bytes) -> str:
    """HMAC-SHA256 of the value under SANITIZE_LOG_KEY, 12 hex chars, for `--detail`: a plain
    hash of a short local value could be guessed (SAN-001.D5)."""
    data = seed.value.encode("utf-8", "surrogatepass")
    return hmac.new(key, data, hashlib.sha256).hexdigest()[:12]


def detail_lines(rows: Sequence[Row], found: Sequence[bool], key: bytes) -> list[str]:
    """Box-only lines: one per residue, a row's short hash, the seed's kind and place and its
    keyed digest. Never a value, a name or a caption."""
    seeds = [(row, seed) for row in rows for seed in row.seeds]
    return [
        f"residue: row {row.short_hash} {seed.kind}/{seed.label or '-'} in {seed.place} "
        f"#{seed_digest(seed, key)}"
        for (row, seed), hit in zip(seeds, found, strict=True)
        if hit
    ]


@dataclass(frozen=True)
class Verdict:
    passed: bool
    lines: tuple[str, ...]


def verdict(synthetic: tuple[bool, str], real: str | None = None) -> Verdict:
    """The exit code follows the synthetic section only (TST-016.D3)."""
    ok, line = synthetic
    lines = (line, *((real,) if real is not None else ()))
    return Verdict(ok, (*lines, f"gate 5 {'PASS' if ok else 'FAIL'}: {CRITERION}"))


# --- The box-only real-name section (DOC-020.D2, TST-016.D2, D4) ------------------------
# fixtures/names_local.txt holds the human's raw file names. No name, nor anything made from
# one (a stem, a rendered name, a matched value), is ever printed, logged, repr'd or put in
# an exception: the section returns one fixed line, and every failure is fixed text.

REAL_HEAD = "real names (box-only, informational)"
REAL_TEMPLATES = ("keep-original", "descriptive")
# The synthetic caption every real name is rendered with: coined, never about an image.
REAL_CAPTION = Caption("qorvex lantern", "zhyndel kite with plimbo", "A quillow beside a drabnet.",
                       ("yskel", "frondak"))  # fmt: skip


class RealNamesError(Exception):
    """The real-name section can't run; fixed text only, never a name or a path."""


@dataclass(frozen=True)
class NameList:
    """The human's file names, held in memory for the section only."""

    names: tuple[str, ...] = field(repr=False)


def read_names_local(path: Path) -> NameList:
    """One name per line, extension included; blank lines and `#` comments skipped.

    A missing file is a failure of the section, never a skip (CLAUDE.md §3). A symlink or a
    non-regular file is refused (privacy item 6), and every read error becomes fixed text,
    raised outside its `except` block, so no OS or codec message (which quotes the path or
    the bytes) is chained.
    """
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise RealNamesError("fixtures/names_local.txt is not a regular file (DOC-020.D2)")
    if not path.exists():
        raise RealNamesError("fixtures/names_local.txt is missing (DOC-020.D2)")
    problem = None
    text = ""
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        problem = "fixtures/names_local.txt is not UTF-8 text (DOC-020.D2)"
    except OSError:
        problem = "fixtures/names_local.txt can't be read (DOC-020.D2)"
    if problem is not None:
        raise RealNamesError(problem)
    lines = (line.strip() for line in text.removeprefix("﻿").splitlines())
    names = tuple(line for line in lines if line and not line.startswith("#"))
    if not names:
        raise RealNamesError("fixtures/names_local.txt holds no name (DOC-020.D2)")
    return NameList(names)


def regex_values(name: str, rules: Iterable[object]) -> list[str]:
    """What each `regex` rule matches in the raw `name`: in memory only, never shown."""
    found = []
    for rule in rules:
        if getattr(rule, "type", None) == "regex":
            found += [m[0] for m in re.finditer(rule.pattern, name) if m[0]]  # type: ignore[attr-defined]
    return found


def real_name_survives(
    name: str, rules: Any, entity: Any, naming: Any, tokens: Sequence[str]
) -> bool:
    """True when a `literal` value, or a `regex` match from the raw name, survives in the
    name's `keep-original` or `descriptive` rendering, or when a `regex` rule still matches a
    rendering. The renderings run as the name node does: the sanitize rules on the name
    (literal, regex and entity, as ingest), then the templates with the R-SAN-7 re-run."""
    from classifier.naming.templates import Tokens, render
    from classifier.sanitize.rules import (
        FILENAME,
        IMAGE_EXTENSIONS,
        sanitize_name,
        sanitize_text,
    )

    def resanitize(text: str) -> str:
        return sanitize_text(text, FILENAME, rules, entity)[0]

    clean = sanitize_name(name.replace("\\", "/").rsplit("/", 1)[-1], rules, entity)
    caption = REAL_CAPTION
    values = Tokens(
        short_hash=hashlib.sha256(name.encode("utf-8", "surrogatepass")).hexdigest()[:8],
        subject=caption.subject,
        detail=caption.detail,
        caption=caption.caption,
        tags=caption.tags,
        original_sanitized=clean.stem,
        ext=clean.suffix,
    )
    rendered = [
        render(BUILTINS[template], values, config=naming, sanitize=resanitize)
        for template in REAL_TEMPLATES
    ]
    # The regex values as the rules see the name: its image extension split off, as
    # sanitize_name does. Taken on the whole name, an email match would run into `.png`,
    # and that probe could never match a rendering, which drops the extension.
    base = PurePosixPath(name.replace("\\", "/")).name
    if PurePosixPath(base).suffix.lower() in IMAGE_EXTENSIONS:
        base = PurePosixPath(base).stem
    probes = [*literal_values(rules.rules), *regex_values(base, rules.rules)]
    seeds = [Seed(LITERAL, "", "path", probe) for probe in probes]
    if any(residues(seeds, rendered, tokens)):
        return True
    patterns = [rule.pattern for rule in rules.rules if getattr(rule, "type", None) == "regex"]
    return any(re.search(pattern, text) for pattern in patterns for text in rendered)


def measure_real_names(path: Path, rules: Any, entity: Any, naming: Any) -> str:
    """The section's one line (TST-016.D2): `ok`, `FAIL`, or `FAIL: <fixed reason>`. Never
    a count, a name, a hash or an example. It never changes the exit code (TST-016.D3)."""
    reason = None
    names: tuple[str, ...] = ()
    try:
        names = read_names_local(path).names
    except RealNamesError as exc:  # fixed text by construction
        reason = str(exc)
    if reason is not None:
        return f"{REAL_HEAD}: FAIL: {reason}"
    tokens = replacement_tokens(rules.rules)
    survived = False
    failed = False
    try:
        survived = any(real_name_survives(n, rules, entity, naming, tokens) for n in names)
    except Exception:  # an error may quote the name: the type isn't shown either
        failed = True
    if failed:
        return (
            f"{REAL_HEAD}: FAIL: a name could not be sanitized or rendered (the entity rule "
            "fails closed: check Ollama and models.text_llm)"
        )
    return f"{REAL_HEAD}: {'FAIL' if survived else 'ok'}"


# --- The run (inside the `test` container) ----------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if any(arg not in ("--detail",) for arg in args):
        print("gate 5 FAIL: usage: gate_5.py [--detail]", file=sys.stderr)
        return 1
    # TST-016.1.3 adds the runner: the caption node (#255) and the name node (#260).
    print(
        "gate 5 FAIL: the runner is not implemented yet (TST-016.1.3, after #255 and #260)",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
