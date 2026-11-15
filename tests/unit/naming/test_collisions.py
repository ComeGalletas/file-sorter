"""NAME-001.2: collisions (R-NAME-6; NAME-001.D3, D6, D7). Synthetic coinages only."""

import logging

import pytest

from classifier.naming.collisions import CollisionError, unique


def test_free_name_is_kept() -> None:
    assert unique("qorvex_001", ".png", set(), has_seq=True) == "qorvex_001.png"
    assert unique("qorvex", ".png", {"zhyndel.png"}, has_seq=False) == "qorvex.png"


def test_comparison_is_casefolded() -> None:
    # NAME-001.D3: NTFS is case-insensitive.
    taken = {"Qorvex_001.PNG"}
    assert unique("qorvex_001", ".png", taken, has_seq=True) == "qorvex_002.png"


def test_same_stem_other_extension_is_free() -> None:
    assert unique("qorvex_001", ".png", {"qorvex_001.gif"}, has_seq=True) == "qorvex_001.png"


def test_seq_increments_keeping_its_width() -> None:
    taken = {"qorvex_001.png", "qorvex_002.png", "qorvex_003.png"}
    assert unique("qorvex_001", ".png", taken, has_seq=True) == "qorvex_004.png"
    assert unique("vexmoor_0007", ".png", {"vexmoor_0007.png"}, has_seq=True) == (
        "vexmoor_0008.png"
    )


def test_seq_grows_past_its_width() -> None:
    assert unique("qorvex_999", ".png", {"qorvex_999.png"}, has_seq=True) == "qorvex_1000.png"


def test_seq_only_stem() -> None:
    # A template such as "{seq:4}" renders digits only.
    assert unique("0001", ".png", {"0001.png"}, has_seq=True) == "0002.png"


def test_no_seq_appends_nnn_from_001() -> None:
    # R-NAME-6 and NAME-001.D6.
    assert unique("qorvex", ".png", {"qorvex.png"}, has_seq=False) == "qorvex_001.png"
    taken = {"qorvex.png", "qorvex_001.png", "QORVEX_002.png"}
    assert unique("qorvex", ".png", taken, has_seq=False) == "qorvex_003.png"


def test_no_seq_ignores_trailing_digits() -> None:
    # A keep-original stem that happens to end in digits is not a seq.
    taken = {"qorvex_0042.png"}
    assert unique("qorvex_0042", ".png", taken, has_seq=False) == "qorvex_0042_001.png"


def test_seq_cut_by_the_cap_appends_nnn() -> None:
    # NAME-001.D5: the cap cut {seq}, so the stem has no trailing digits.
    taken = {"plimmerkrandle_quarbish.png"}
    out = unique("plimmerkrandle_quarbish", ".png", taken, has_seq=True)
    assert out == "plimmerkrandle_quarbish_001.png"


def test_the_runs_own_proposals_count() -> None:
    taken: set[str] = set()
    names = []
    for _ in range(3):
        name = unique("qorvex_001", ".png", taken, has_seq=True)
        names.append(name)
        taken.add(name)  # the caller (the name node) records each result
    assert names == ["qorvex_001.png", "qorvex_002.png", "qorvex_003.png"]


def test_taken_is_not_mutated() -> None:
    taken = {"qorvex.png"}
    unique("qorvex", ".png", taken, has_seq=False)
    assert taken == {"qorvex.png"}


def test_never_returns_a_taken_name() -> None:
    taken = {f"qorvex_{n:03d}.png" for n in range(1, 300)} | {"qorvex.png"}
    out = unique("qorvex", ".png", taken, has_seq=False)
    assert out.casefold() not in {t.casefold() for t in taken}
    assert out == "qorvex_300.png"


def test_empty_extension() -> None:
    assert unique("qorvex", "", {"qorvex"}, has_seq=False) == "qorvex_001"


# --- max_len (NAME-001.D7) ----------------------------------------------------------------


def test_max_len_trims_the_tail_to_fit_the_suffix() -> None:
    stem = "q" * 120
    out = unique(stem, ".png", {stem + ".png"}, has_seq=False, max_len=120)
    assert out == "q" * 116 + "_001.png"
    assert len(out) - len(".png") == 120


def test_max_len_strips_a_dangling_underscore_before_the_suffix() -> None:
    stem = "q" * 115 + "_vexm"  # 120; trimming to 116 leaves "q"*115 + "_"
    out = unique(stem, ".png", {stem + ".png"}, has_seq=False, max_len=120)
    assert out == "q" * 115 + "_001.png"


def test_max_len_with_a_growing_seq() -> None:
    stem = "q" * 116 + "_999"
    out = unique(stem, ".png", {stem + ".png"}, has_seq=True, max_len=120)
    assert out == "q" * 115 + "_1000.png"
    assert len(out) - len(".png") == 120


def test_max_len_rechecks_the_trimmed_name() -> None:
    # The trimmed candidate itself is taken, so the next number is used.
    stem = "q" * 120
    taken = {stem + ".png", "q" * 116 + "_001.png"}
    out = unique(stem, ".png", taken, has_seq=False, max_len=120)
    assert out == "q" * 116 + "_002.png"


def test_max_len_caps_an_overlong_free_stem() -> None:
    assert unique("q" * 130, ".png", set(), has_seq=False, max_len=120) == "q" * 120 + ".png"


def test_without_max_len_nothing_is_trimmed() -> None:
    stem = "q" * 120
    out = unique(stem, ".png", {stem + ".png"}, has_seq=False)
    assert out == stem + "_001.png"


# --- errors -------------------------------------------------------------------------------

PLANT = "Zhyndel"


@pytest.mark.parametrize(
    ("stem", "ext", "max_len"),
    [
        pytest.param("", ".png", None, id="empty-stem"),
        pytest.param(PLANT, "png", None, id="ext-without-dot"),
        pytest.param(PLANT, "." + PLANT + "x" * 10, None, id="ext-too-long"),
        pytest.param(PLANT, ".p/ng", None, id="ext-with-slash"),
        pytest.param(PLANT, "." + PLANT + "\udcff", None, id="ext-surrogate"),
        pytest.param(PLANT, ".png", 0, id="max-len-zero"),
    ],
)
def test_bad_input_raises_fixed_text_unchained(stem: str, ext: str, max_len: int | None) -> None:
    with pytest.raises(CollisionError) as caught:
        unique(stem, ext, set(), has_seq=False, max_len=max_len)
    error = caught.value
    assert error.__cause__ is None and error.__context__ is None
    assert PLANT not in str(error) and PLANT not in repr(error)


def test_unique_prints_and_logs_nothing(
    capsys: pytest.CaptureFixture[str], caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    out = unique("qorvex_001", ".png", {"qorvex_001.png"}, has_seq=True)
    assert out == "qorvex_002.png"  # a name was made...
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err == ""  # ...and nothing printed it
    assert caplog.records == []
