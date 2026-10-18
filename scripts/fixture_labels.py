"""Load and validate fixtures/labels.csv (TST-008.2; CLS-001.D10, D11, D12, D14).

QA owns this file. The labels are the human's private data: every field of a row is
``repr=False``, and an error names a line number and a column, never a value (TST-008.D5).
Line numbers count physical CSV lines with the header as line 1; a quoted cell that spans
lines is reported at the first line of its record.
"""

import csv
import io
import stat
from collections.abc import Collection
from dataclasses import dataclass, field
from pathlib import Path

COLUMNS = ("file", "format", "topic", "adult", "reference", "subject", "tags")
LEVEL_COLUMN = "nsfw_level"  # optional, trailing (TST-009.D1)
# The NsfwLevel names in order (classifier/config.py); the loader stays free of `classifier`.
LEVELS = ("safe", "suggestive", "nudity", "explicit")
TAG_SUGGESTIVE_NEGATIVE = "suggestive-negative"
TAG_CALIBRATION_ONLY = "calibration-only"
TAGS = frozenset({TAG_SUGGESTIVE_NEGATIVE, TAG_CALIBRATION_ONLY})

_BAD_HEADER = "header is not the expected columns"
_BAD_CELLS = "wrong number of cells"
_BAD_CSV = "malformed CSV"
_BAD_ADULT = "must be yes or no"
_BAD_LEVEL = "must be blank, safe, suggestive, nudity or explicit"
_BLANK_FILE = "must not be blank"
_UNKNOWN_FORMAT = "not in the format vocabulary"
_UNKNOWN_TOPIC = "not in the topic vocabulary"
_SAME_AXES = "topic repeats the format"
_UNKNOWN_TAG = "unknown tag"
_CONTRADICTION = "suggestive-negative cannot be adult"
_DUPLICATE = "duplicate file"
_UNREADABLE = "cannot read the labels file"
_NOT_REGULAR = "the labels path is not a regular file"
_BAD_ENCODING = "the labels file is not valid UTF-8"


class LabelsError(ValueError):
    """A labels problem. The text holds a line number and a column name, never a value."""


@dataclass(frozen=True)
class LabelRow:
    file: str = field(repr=False)
    format: str | None = field(repr=False)
    topic: str | None = field(repr=False)
    adult: bool = field(repr=False)
    reference: str = field(repr=False)
    subject: str = field(repr=False)
    tags: frozenset[str] = field(repr=False)
    nsfw_level: str | None = field(default=None, repr=False)  # TST-009.D1
    line: int = field(default=0, repr=False)  # the physical CSV line, for gate errors

    def expects_adult(self, min_level: int) -> bool:
        """TST-009.D1: with a level the row is adult when its rank is >= `min_level`;
        without one the `adult` column stands."""
        if self.nsfw_level is None:
            return self.adult
        return LEVELS.index(self.nsfw_level) >= min_level


@dataclass(frozen=True)
class LabelSet:
    rows: tuple[LabelRow, ...] = field(repr=False)

    def gate_rows(self) -> tuple[LabelRow, ...]:
        """The rows every gate measure counts: those not tagged calibration-only (TST-008.D2)."""
        return tuple(r for r in self.rows if TAG_CALIBRATION_ONLY not in r.tags)

    def suggestive_negatives(self) -> tuple[LabelRow, ...]:
        """The gate rows tagged suggestive-negative (CLS-001.D12)."""
        return tuple(r for r in self.gate_rows() if TAG_SUGGESTIVE_NEGATIVE in r.tags)

    def calibration_rows(self) -> tuple[LabelRow, ...]:
        """The rows tagged calibration-only, for the NSFW sweep only (TST-008.D2)."""
        return tuple(r for r in self.rows if TAG_CALIBRATION_ONLY in r.tags)


def _fail(line: int, column: str, reason: str) -> LabelsError:
    return LabelsError(f"labels line {line}, column {column}: {reason}")


def parse_labels(text: str, *, formats: Collection[str], topics: Collection[str]) -> LabelSet:
    """Parse labels text. ``formats`` and ``topics`` are the vocabularies the caller read."""
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[LabelRow] = []
    seen: set[str] = set()
    csv_broken_at = 0
    header_seen = False
    width = len(COLUMNS)
    start = 1
    try:
        for cells in reader:
            line = start
            start = reader.line_num + 1
            if not header_seen:
                header_seen = True
                head = tuple(c.strip() for c in cells)
                if head not in (COLUMNS, (*COLUMNS, LEVEL_COLUMN)):
                    raise _fail(line, "header", _BAD_HEADER)
                width = len(head)
                continue
            if not cells:
                continue
            if len(cells) != width:
                raise _fail(line, "row", _BAD_CELLS)
            row = _row(line, cells, formats, topics)
            if row.file in seen:
                raise _fail(line, "file", _DUPLICATE)
            seen.add(row.file)
            rows.append(row)
    except csv.Error:
        csv_broken_at = start
    if csv_broken_at:
        raise _fail(csv_broken_at, "row", _BAD_CSV)
    if not header_seen:
        raise _fail(1, "header", _BAD_HEADER)
    return LabelSet(rows=tuple(rows))


def _row(
    line: int, cells: list[str], formats: Collection[str], topics: Collection[str]
) -> LabelRow:
    file, fmt, topic, adult, reference, subject, tags, *rest = (c.strip() for c in cells)
    level = rest[0] if rest else ""
    if not file:
        raise _fail(line, "file", _BLANK_FILE)
    if adult not in ("yes", "no"):
        raise _fail(line, "adult", _BAD_ADULT)
    if level and level not in LEVELS:
        raise _fail(line, LEVEL_COLUMN, _BAD_LEVEL)
    if fmt and fmt not in formats:
        raise _fail(line, "format", _UNKNOWN_FORMAT)
    if topic and topic not in topics:
        raise _fail(line, "topic", _UNKNOWN_TOPIC)
    if fmt and fmt == topic:
        raise _fail(line, "topic", _SAME_AXES)  # CLS-001.D10
    tag_set = frozenset(t.strip() for t in tags.replace(";", ",").split(",") if t.strip())
    if not tag_set <= TAGS:
        raise _fail(line, "tags", _UNKNOWN_TAG)
    if adult == "yes" and TAG_SUGGESTIVE_NEGATIVE in tag_set:
        raise _fail(line, "tags", _CONTRADICTION)  # CLS-001.D12
    return LabelRow(
        file=file,
        format=fmt or None,
        topic=topic or None,
        adult=adult == "yes",
        reference=reference,
        subject=subject,
        tags=tag_set,
        nsfw_level=level or None,
        line=line,
    )


def load_labels(path: Path, *, formats: Collection[str], topics: Collection[str]) -> LabelSet:
    """Read and parse the labels file. Refuses anything but a regular file; no path in errors."""
    problem = ""
    data = b""
    try:
        if not stat.S_ISREG(path.lstat().st_mode):
            problem = _NOT_REGULAR
        else:
            data = path.read_bytes()
    except (OSError, ValueError):  # ValueError: a NUL in the path
        problem = _UNREADABLE
    if problem:
        raise LabelsError(f"labels file: {problem}")
    text = ""
    try:
        text = data.decode("utf-8-sig", errors="surrogatepass")
    except UnicodeError:
        problem = _BAD_ENCODING
    if problem:
        raise LabelsError(f"labels file: {problem}")
    return parse_labels(text, formats=formats, topics=topics)
