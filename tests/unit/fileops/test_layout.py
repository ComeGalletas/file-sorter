"""FOP-002.1: the result folder layout. Synthetic, unmistakably artificial names only."""

from pathlib import PurePosixPath

import pytest

from classifier.config import FoldersConfig
from classifier.fileops.layout import LayoutError, result_folder

NSFW_ROOT = "Zorblax"
NO_TOPIC = "Plinth"


def _folders(*, animated_subfolder: bool = False, layout: str = "{topic}/{format}"):
    return FoldersConfig(
        auto_create=True,
        layout=layout,
        no_topic=NO_TOPIC,
        animated_subfolder=animated_subfolder,
    )


def _folder(
    *,
    branch="safe",
    topic_path=("Qorvex",),
    format_folder="Zhyndel",
    animated=False,
    folders=None,
):
    return result_folder(
        branch=branch,
        topic_path=topic_path,
        format_folder=format_folder,
        animated=animated,
        folders=folders or _folders(),
        nsfw_root=NSFW_ROOT,
    )


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({}, "Qorvex/Zhyndel"),
        ({"topic_path": ()}, "Plinth/Zhyndel"),
        ({"branch": "nsfw"}, "Zorblax/Qorvex/Zhyndel"),
        ({"branch": "nsfw", "topic_path": ()}, "Zorblax/Plinth/Zhyndel"),
        ({"format_folder": None}, "Unsorted"),
        ({"format_folder": None, "branch": "nsfw"}, "Zorblax/Unsorted"),
        # a topic is ignored for unsorted: the format decides first (R-CLS-5)
        ({"format_folder": None, "topic_path": ("Qorvex",)}, "Unsorted"),
    ],
)
def test_layout_table(kwargs, expected):
    assert _folder(**kwargs) == PurePosixPath(expected)


@pytest.mark.parametrize("animated", [False, True])
def test_animated_off_by_default(animated):
    assert _folder(animated=animated) == PurePosixPath("Qorvex/Zhyndel")


@pytest.mark.parametrize(
    ("animated", "branch", "expected"),
    [
        (True, "safe", "Qorvex/Zhyndel/Animated"),
        (True, "nsfw", "Zorblax/Qorvex/Zhyndel/Animated"),
        (False, "safe", "Qorvex/Zhyndel"),
    ],
)
def test_animated_subfolder_needs_both_flags(animated, branch, expected):
    folders = _folders(animated_subfolder=True)
    assert _folder(animated=animated, branch=branch, folders=folders) == PurePosixPath(expected)


def test_animated_never_applies_to_unsorted():
    folders = _folders(animated_subfolder=True)
    assert _folder(format_folder=None, animated=True, folders=folders) == PurePosixPath("Unsorted")


def test_result_is_relative():
    assert not _folder(branch="nsfw").is_absolute()


def test_other_layout_fails_fast():
    with pytest.raises(LayoutError, match="folders.layout"):
        _folder(folders=_folders(layout="{format}/{topic}"))


def test_unknown_branch_is_refused():
    with pytest.raises(LayoutError):
        _folder(branch="both")
