"""FOP-002.1: the result folder layout. Synthetic, unmistakably artificial names only."""

from pathlib import PurePosixPath

import pytest

from classifier.config import FoldersConfig
from classifier.fileops.layout import LayoutError, result_folder, validate_folder_segment

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


def test_nested_topic_is_parent_folder_plus_its_own():
    assert _folder(topic_path=("Qorvex", "Vlimp")) == PurePosixPath("Qorvex/Vlimp/Zhyndel")
    assert _folder(topic_path=("Qorvex", "Vlimp"), branch="nsfw") == PurePosixPath(
        "Zorblax/Qorvex/Vlimp/Zhyndel"
    )


def test_case_is_left_alone():
    assert _folder(topic_path=("qORvex",), format_folder="ZHYNDEL") == PurePosixPath(
        "qORvex/ZHYNDEL"
    )


BAD_SEGMENTS = [
    "",
    ".",
    "..",
    "a/b",
    "a\\b",
    "C:",
    "a:stream",
    "a\x00b",
    "a\nb",
    "a*b",
    'a"b',
    "a ",
    "a.",
    "NUL",
    "con.txt",
    "lpt1",
    "a\ud800b",
    None,
    7,
]


@pytest.mark.parametrize("bad", BAD_SEGMENTS)
@pytest.mark.parametrize("where", ["topic", "nested", "format"])
def test_bad_segment_is_refused(where, bad):
    if where == "format" and bad is None:
        return  # None is the `unsorted` format, not a bad name
    kwargs = dict(
        topic=dict(topic_path=(bad,)),
        nested=dict(topic_path=("Qorvex", bad)),
        format=dict(format_folder=bad),
    )[where]
    with pytest.raises(LayoutError, match="invalid folder name"):
        _folder(**kwargs)


@pytest.mark.parametrize("bad", BAD_SEGMENTS)
def test_bad_no_topic_and_nsfw_root_are_refused(bad):
    no_topic = FoldersConfig.model_construct(
        auto_create=True, layout="{topic}/{format}", no_topic=bad, animated_subfolder=False
    )
    with pytest.raises(LayoutError, match="invalid folder name"):
        _folder(topic_path=(), folders=no_topic)
    with pytest.raises(LayoutError, match="invalid folder name"):
        result_folder(
            branch="nsfw",
            topic_path=("Qorvex",),
            format_folder="Zhyndel",
            animated=False,
            folders=_folders(),
            nsfw_root=bad,
        )


PLANTED = "Qzyx<planted>Vlorp"  # an invalid segment that must never reach an error


def _raised(**kwargs) -> LayoutError:
    with pytest.raises(LayoutError) as caught:
        _folder(**kwargs)
    return caught.value


@pytest.mark.parametrize(
    "kwargs",
    [
        {"topic_path": (PLANTED,)},
        {"format_folder": PLANTED},
        {"branch": PLANTED},
        {"folders": _folders(layout=PLANTED)},
    ],
)
def test_errors_are_fixed_text_and_unchained(kwargs):
    error = _raised(**kwargs)
    assert "Qzyx" not in repr(error) + str(error) + repr(error.args)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_unpaired_surrogate_is_refused_without_quoting_it():
    error = _raised(topic_path=("Qzyx\ud800Vlorp",))
    assert "Qzyx" not in repr(error) + str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_bad_nsfw_root_is_ignored_on_the_safe_branch():
    assert result_folder(
        branch="safe",
        topic_path=("Qorvex",),
        format_folder="Zhyndel",
        animated=False,
        folders=_folders(),
        nsfw_root="..",
    ) == PurePosixPath("Qorvex/Zhyndel")


@pytest.mark.parametrize("name", ["Qorvex", "Zhyndel Vo", "a.b"])
def test_validate_folder_segment_returns_a_safe_name(name: str) -> None:
    assert validate_folder_segment(name) == name


@pytest.mark.parametrize(
    "name", ["", ".", "..", "a/b", "a\b", "a:b", "nul", "Con.txt", "x.", "x ", "a\ud800b", "a\x00"]
)
def test_validate_folder_segment_refuses_a_bad_name_with_fixed_text(name: str) -> None:
    with pytest.raises(LayoutError) as caught:
        validate_folder_segment(name)
    assert str(caught.value) == "invalid folder name"
    assert caught.value.__cause__ is None
