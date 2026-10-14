"""The result folder for a file (FOP-002.1, R-CLS-5, R-ING-9).

Pure: no file system, no logging. The caller joins the returned relative path onto
`results_root`. `LayoutError` carries a fixed text and never a value (CLAUDE.md "Hard rules").
"""

from collections.abc import Sequence
from pathlib import PurePosixPath
from typing import Literal

from classifier.config import FoldersConfig

SUPPORTED_LAYOUT = "{topic}/{format}"  # FOP-002.D1
UNSORTED_FOLDER = "Unsorted"  # R-CLS-5: the folder of the `unsorted` format
ANIMATED_FOLDER = "Animated"  # R-ING-9

Branch = Literal["safe", "nsfw"]


class LayoutError(Exception):
    """The layout cannot be built. The message is a fixed text with no value in it."""


_ERR_LAYOUT = "unsupported folders.layout"
_ERR_BRANCH = "invalid branch"
_ERR_SEGMENT = "invalid folder name"


def result_folder(
    *,
    branch: Branch,
    topic_path: Sequence[str],
    format_folder: str | None,
    animated: bool,
    folders: FoldersConfig,
    nsfw_root: str,
) -> PurePosixPath:
    """`[nsfw_root/]<topic path | no_topic>/<format>[/Animated]`, or `[nsfw_root/]Unsorted`.

    `topic_path` runs from the root category down to the chosen topic (empty: no topic).
    `format_folder=None` means the `unsorted` format.
    """
    if folders.layout != SUPPORTED_LAYOUT:
        raise LayoutError(_ERR_LAYOUT)
    if branch not in ("safe", "nsfw"):
        raise LayoutError(_ERR_BRANCH)
    parts: list[str] = [nsfw_root] if branch == "nsfw" else []
    if format_folder is None:
        parts.append(UNSORTED_FOLDER)
    else:
        parts.extend(topic_path or [folders.no_topic])
        parts.append(format_folder)
        if animated and folders.animated_subfolder:
            parts.append(ANIMATED_FOLDER)
    return PurePosixPath(*parts)
