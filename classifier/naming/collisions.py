"""NAME-001.2: collisions (R-NAME-6). Pure: no I/O, no logging.

`unique()` returns `stem + ext`, made unique against `taken`, compared casefolded (NTFS,
NAME-001.D3). `taken` holds the run's earlier proposals plus the names already under the
target folder in `results/`; the caller adds each result to it. Errors are fixed text and
never quote the stem or the extension (privacy item 19).
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_EXT = re.compile(r"(\.[A-Za-z0-9]{1,15})?")  # files.ext is String(16)
_TRAILING_SEQ = re.compile(r"(.*?)(_*)([0-9]+)")
_MIN_LEN = len("_001")  # a shorter cap couldn't hold the suffix (#269 review)


class CollisionError(ValueError):
    """Bad input to `unique()`. The message is fixed text."""


def _fit(body: str, rest: str, max_len: int | None) -> str:
    # NAME-001.D7: trim the stem's tail so body + rest fit, keeping the head (NAME-001.D5).
    # A dangling "_" is stripped only after a trim or before a suffix: a free name that
    # fits comes back unchanged.
    if max_len is not None and len(body) + len(rest) > max_len:
        body = body[: max(max_len - len(rest), 0)].rstrip("_")
    elif rest:
        body = body.rstrip("_")
    return (body + rest) if body else rest.lstrip("_")


def unique(
    stem: str,
    ext: str,
    taken: Iterable[str],
    *,
    has_seq: bool,
    max_len: int | None = None,
) -> str:
    """The first free name, never one in `taken` (R-NAME-6: never overwrite).

    - Free already: `stem + ext`.
    - `has_seq` and the stem ends in digits (the rendered `{seq}`, last in every built-in
      that has one): increment them, keeping their zero-pad width and growing past it.
    - Otherwise, including a `{seq}` the cap cut (NAME-001.D5): append `_001`, `_002`, ...
      (NAME-001.D6).
    - `max_len` caps the stem, suffix included (NAME-001.D7).
    """
    if not isinstance(stem, str) or not stem:
        raise CollisionError("stem is empty")
    if not isinstance(ext, str) or _EXT.fullmatch(ext) is None:
        raise CollisionError("extension must be empty or a dot and 1 to 15 letters or digits")
    if max_len is not None and max_len < _MIN_LEN:
        raise CollisionError("max_len must be at least 4, the length of a _NNN suffix")
    seen = {name.casefold() for name in taken}

    def free(candidate: str) -> bool:
        return (candidate + ext).casefold() not in seen

    base = _fit(stem, "", max_len)
    if base and free(base):
        return base + ext

    found = _TRAILING_SEQ.fullmatch(stem) if has_seq else None
    if found is not None:
        body, sep, digits = found.groups()  # the separator is kept as rendered
        width, number = len(digits), int(digits) + 1
    else:
        body, sep, width, number = stem, "_", 3, 1

    while True:
        candidate = _fit(body, sep + str(number).zfill(width), max_len)
        if free(candidate):
            return candidate + ext
        number += 1
