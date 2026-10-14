"""The classify node: `sanitized` → `classified` (CLS-002.2, R-CLS-0 to R-CLS-6, R-PIPE-1, P-2).

The node reads only the sanitized working copy `<results_root>/.work/<source_hash>.<ext>`,
a path built from the hash and the extension, never from `source_path` (CLS-002.D8, P-2).
Models get decoded pixels only, through `classifier/models/`. It never writes a file and
never commits; `run` commits once per node (PIPE-001.D3).

Logs carry short hashes, counts and fixed reasons only (DOC-007.D1). Errors are fixed text,
raised outside the `except` block so `__cause__` and `__context__` stay None.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from classifier.config import Config

_SEPARATE_UNSUPPORTED = "nsfw.mode: separate is not supported in M3; set it to mirror"


class ClassifyConfigError(Exception):
    """A setting M3 doesn't support. Names the key only, never a value (CLS-002.D9)."""


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
