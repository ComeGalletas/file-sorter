"""Load and validate fixtures/labels.csv (TST-008.2; CLS-001.D10, D11, D12, D14).

QA owns this file. The labels are the human's private data: every field of a row is
``repr=False``, and an error names a line number and a column, never a value (TST-008.D5).
Line numbers count physical CSV lines with the header as line 1; a quoted cell that spans
lines is reported at the first line of its record.
"""

import csv
import io
from collections.abc import Collection
from dataclasses import dataclass, field

COLUMNS = ("file", "format", "topic", "adult", "reference", "subject", "tags")
TAG_SUGGESTIVE_NEGATIVE = "suggestive-negative"
TAG_CALIBRATION_ONLY = "calibration-only"
TAGS = frozenset({TAG_SUGGESTIVE_NEGATIVE, TAG_CALIBRATION_ONLY})

_BAD_HEADER = "header is not the expected columns"
_BAD_CELLS = "wrong number of cells"
_BAD_CSV = "malformed CSV"
_BAD_ADULT = "must be yes or no"
_BLANK_FILE = "must not be blank"


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


@dataclass(frozen=True)
class LabelSet:
    rows: tuple[LabelRow, ...] = field(repr=False)


def _fail(line: int, column: str, reason: str) -> LabelsError:
    return LabelsError(f"labels line {line}, column {column}: {reason}")


def parse_labels(text: str, *, formats: Collection[str], topics: Collection[str]) -> LabelSet:
    """Parse labels text. ``formats`` and ``topics`` are the vocabularies the caller read."""
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[LabelRow] = []
    csv_broken_at = 0
    header_seen = False
    start = 1
    try:
        for cells in reader:
            line = start
            start = reader.line_num + 1
            if not header_seen:
                header_seen = True
                if tuple(c.strip() for c in cells) != COLUMNS:
                    raise _fail(line, "header", _BAD_HEADER)
                continue
            if not cells:
                continue
            if len(cells) != len(COLUMNS):
                raise _fail(line, "row", _BAD_CELLS)
            rows.append(_row(line, cells))
    except csv.Error:
        csv_broken_at = start
    if csv_broken_at:
        raise _fail(csv_broken_at, "row", _BAD_CSV)
    if not header_seen:
        raise _fail(1, "header", _BAD_HEADER)
    return LabelSet(rows=tuple(rows))


def _row(line: int, cells: list[str]) -> LabelRow:
    file, fmt, topic, adult, reference, subject, tags = (c.strip() for c in cells)
    if not file:
        raise _fail(line, "file", _BLANK_FILE)
    if adult not in ("yes", "no"):
        raise _fail(line, "adult", _BAD_ADULT)
    return LabelRow(
        file=file,
        format=fmt or None,
        topic=topic or None,
        adult=adult == "yes",
        reference=reference,
        subject=subject,
        tags=frozenset(),
    )
