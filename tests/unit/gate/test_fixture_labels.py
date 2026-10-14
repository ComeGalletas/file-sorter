"""TST-008.2: the labels loader and validator (TST-008.D2, D5; CLS-001.D10, D11, D12, D14).

Synthetic CSV text only, with artificial coinages for every name and category. The real
fixtures/labels.csv is never read here (TST-004).
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "fixture_labels.py"
_spec = importlib.util.spec_from_file_location("fixture_labels", SCRIPT)
assert _spec is not None and _spec.loader is not None
fl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fl)

HEADER = "file,format,topic,adult,reference,subject,tags\n"
FORMATS = {"zorbs", "qwims"}
TOPICS = {"zorbs", "qwims", "plinth"}


def parse(body: str, header: str = HEADER):
    return fl.parse_labels(header + body, formats=FORMATS, topics=TOPICS)


def error_of(body: str, header: str = HEADER) -> fl.LabelsError:
    with pytest.raises(fl.LabelsError) as info:
        parse(body, header)
    return info.value


def test_parses_a_row_with_blank_axes_as_none() -> None:
    result = parse("a1.zz,zorbs,,no,Ref One,sub one,\nb2.zz,,plinth,yes,,,\n")
    first, second = result.rows
    assert (first.format, first.topic, first.adult) == ("zorbs", None, False)
    assert (second.format, second.topic, second.adult) == (None, "plinth", True)
    assert (first.reference, first.subject) == ("Ref One", "sub one")
    assert (second.reference, second.subject) == ("", "")


def test_blank_lines_are_skipped() -> None:
    assert len(parse("a1.zz,zorbs,,no,,,\n\n").rows) == 1


@pytest.mark.parametrize(
    "header",
    [
        "",
        "file,format,topic,adult,reference,subject\n",
        "file,topic,format,adult,reference,subject,tags\n",
        "file,format,topic,adult,reference,subject,tags,extra\n",
    ],
)
def test_bad_header_names_line_one(header: str) -> None:
    error = error_of("", header)
    assert str(error) == "labels line 1, column header: header is not the expected columns"


def test_wrong_cell_count_names_the_row_line() -> None:
    error = error_of("a1.zz,zorbs,,no,,,\nQORVEX-SECRET,zorbs\n")
    assert str(error) == "labels line 3, column row: wrong number of cells"
    assert "QORVEX" not in str(error)


def test_a_quoted_cell_spanning_lines_reports_its_first_line() -> None:
    body = 'a1.zz,zorbs,,no,"two\nlines",sub,\nb2.zz,zorbs,,maybe,,,\n'
    assert str(error_of(body)) == "labels line 4, column adult: must be yes or no"
    body = 'a1.zz,zorbs,,no,"two\nlines",sub,\nb2.zz,zorbs\n'
    assert str(error_of(body)) == "labels line 4, column row: wrong number of cells"
    body = 'a1.zz,zorbs,,maybe,"two\nlines",sub,\n'
    assert str(error_of(body)) == "labels line 2, column adult: must be yes or no"


@pytest.mark.parametrize("adult", ["", "maybe", "Yes", "true"])
def test_adult_must_be_yes_or_no(adult: str) -> None:
    error = error_of(f"a1.zz,zorbs,,{adult},,,\n")
    assert str(error) == "labels line 2, column adult: must be yes or no"


def test_blank_file_is_an_error() -> None:
    assert str(error_of(",zorbs,,no,,,\n")) == "labels line 2, column file: must not be blank"


def test_malformed_csv_is_unchained_and_names_a_line() -> None:
    error = error_of("a1.zz,zorbs,,no,," + "x" * 200_000 + ",\n")
    assert str(error) == "labels line 2, column row: malformed CSV"
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.mark.parametrize(
    "body",
    ["QORVEX-SECRET,zorbs\n", "a1.zz,zorbs,,QORVEX-SECRET,,,\n", ",zorbs,,no,,,\n"],
)
def test_errors_are_unchained(body: str) -> None:
    error = error_of(body)
    assert error.__cause__ is None
    assert error.__context__ is None
    assert "QORVEX" not in str(error)


def test_repr_and_str_hide_every_planted_value() -> None:
    secrets = ["QorvexFile.zz", "zorbs", "plinth", "Zhyndel Reference", "Zhyndel subject"]
    result = parse("QorvexFile.zz,zorbs,plinth,no,Zhyndel Reference,Zhyndel subject,\n")
    row = result.rows[0]
    for obj in (row, result):
        for text in (repr(obj), str(obj), f"{obj}", f"{obj!r}"):
            for secret in secrets:
                assert secret not in text
