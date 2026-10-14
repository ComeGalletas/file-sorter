"""The classify node: `sanitized` → `classified` (CLS-002.2, R-CLS-0 to R-CLS-6, R-PIPE-1, P-2).

The node reads only the sanitized working copy `<results_root>/.work/<source_hash>.<ext>`,
a path built from the hash and the extension, never from `source_path` (CLS-002.D8, P-2).
Models get decoded pixels only, through `classifier/models/`. It never writes a file and
never commits; `run` commits once per node (PIPE-001.D3).

Logs carry short hashes, counts and fixed reasons only (DOC-007.D1). Errors are fixed text,
raised outside the `except` block so `__cause__` and `__context__` stay None.
"""

import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType

from PIL import Image

from classifier.config import Config
from classifier.fileops.copy_move import working_copy_name

WORKING_COPY_UNREADABLE = "classify_working_copy_unreadable"  # CLS-002.D7
_SEPARATE_UNSUPPORTED = "nsfw.mode: separate is not supported in M3; set it to mirror"


class ClassifyConfigError(Exception):
    """A setting M3 doesn't support. Names the key only, never a value (CLS-002.D9)."""


class WorkingCopyUnreadable(Exception):
    """One working copy is missing, linked, not a regular file or not decodable (CLS-002.D7).

    Fixed text only: the library and OS messages carry the path, so they are dropped.
    """

    reason = WORKING_COPY_UNREADABLE

    def __init__(self) -> None:
        super().__init__(WORKING_COPY_UNREADABLE)


@dataclass(frozen=True)
class ClassifyResult:
    """What one classify run did: counts and fixed reasons only (CLI-005 and gate 3 read them).

    `classified` counts every row that reached `classified`; `unsorted`, `no_topic` and
    `adult` are subsets of it. `errored` rows are not in `classified`.
    """

    classified: int = 0
    unsorted: int = 0
    no_topic: int = 0
    adult: int = 0
    errored: int = 0
    by_reason: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    @property
    def total(self) -> int:
        return self.classified + self.errored


def check_settings(config: Config) -> None:
    """Fail fast on settings M3 doesn't support, naming the key only (CLS-002.D9)."""
    if config.nsfw.mode != "mirror":
        raise ClassifyConfigError(_SEPARATE_UNSUPPORTED)


def open_working_copy(work: Path, source_hash: str, ext: str) -> Image.Image:
    """Decode the first frame of one working copy as RGB (R-ING-6, CLS-002.D8).

    The name comes from `working_copy_name`, the helper sanitize publishes through. The file
    is opened with `O_NOFOLLOW` (a link is refused) and `O_NONBLOCK` (a pipe can't hang the
    run), and must be a regular file by `fstat` on the open descriptor. Any failure raises
    `WorkingCopyUnreadable`, unchained.
    """
    image: Image.Image | None = None
    try:
        path = work / working_copy_name(source_hash, ext)
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            handle = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                raise OSError("not a regular file")
            with Image.open(handle) as opened:
                opened.seek(0)  # R-ING-6: the first frame only
                image = opened.convert("RGB")  # loads the pixels before the file closes
    except Exception:
        image = None
    if image is None:
        raise WorkingCopyUnreadable
    return image
