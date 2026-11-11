"""API-001.5.1: `esc`, the one escaping helper (API-001.D4, m4 privacy item 12)."""

import pytest

from classifier.ui.html import DASH, esc


@pytest.mark.parametrize(
    ("value", "want"),
    [
        ("<script>alert(1)</script>", "&lt;script&gt;alert(1)&lt;/script&gt;"),
        ('Qorvex" onmouseover="x', "Qorvex&quot; onmouseover=&quot;x"),
        ("Zhyndel' onload='x", "Zhyndel&#x27; onload=&#x27;x"),
        ("a & b", "a &amp; b"),
        ("&lt;", "&amp;lt;"),  # already-escaped text is escaped again, never trusted
        ("plain-qorvex.png", "plain-qorvex.png"),
    ],
)
def test_esc_makes_markup_inert(value: str, want: str) -> None:
    assert esc(value) == want


@pytest.mark.parametrize("value", ["<", ">", '"', "'", "<img src=x>", '"><script>'])
def test_esc_output_has_no_markup_characters(value: str) -> None:
    out = esc(value)
    assert not any(c in out for c in "<>\"'")


def test_esc_none_is_a_fixed_dash() -> None:
    assert esc(None) == DASH


def test_esc_bools_and_numbers() -> None:
    assert esc(True) == "yes"
    assert esc(False) == "no"
    assert esc(0) == "0"
    assert esc(12.5) == "12.5"


def test_esc_non_str_goes_through_str_then_escape() -> None:
    class Odd:
        def __str__(self) -> str:
            return "<b>Qorvex</b>"

    assert esc(Odd()) == "&lt;b&gt;Qorvex&lt;/b&gt;"
