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


# --- TST-008.2.2: vocabulary, tags, duplicates and the file-level read ---


def test_unknown_format_and_topic_name_their_column() -> None:
    assert str(error_of("a1.zz,blorp,,no,,,\n")) == (
        "labels line 2, column format: not in the format vocabulary"
    )
    assert str(error_of("a1.zz,zorbs,blorp,no,,,\n")) == (
        "labels line 2, column topic: not in the topic vocabulary"
    )


def test_topic_may_not_repeat_the_format() -> None:
    assert str(error_of("a1.zz,zorbs,zorbs,no,,,\n")) == (
        "labels line 2, column topic: topic repeats the format"
    )


def test_a_topic_that_is_also_a_format_name_is_fine_when_different() -> None:
    assert parse("a1.zz,zorbs,qwims,no,,,\n").rows[0].topic == "qwims"


def test_tags_accept_both_separators_and_whitespace() -> None:
    rows = parse(
        "a1.zz,zorbs,,no,,,suggestive-negative\n"
        'b2.zz,zorbs,,no,,,"suggestive-negative; calibration-only"\n'
        'c3.zz,zorbs,,yes,,,"calibration-only , "\n'
        "d4.zz,zorbs,,no,,,   \n"
    ).rows
    assert rows[0].tags == {"suggestive-negative"}
    assert rows[1].tags == {"suggestive-negative", "calibration-only"}
    assert rows[2].tags == {"calibration-only"}
    assert rows[3].tags == frozenset()


def test_unknown_tag_stops_the_load() -> None:
    error = error_of("a1.zz,zorbs,,no,,,qorvex-tag\n")
    assert str(error) == "labels line 2, column tags: unknown tag"
    assert "qorvex" not in str(error)


def test_suggestive_negative_cannot_be_adult() -> None:
    assert str(error_of("a1.zz,zorbs,,yes,,,suggestive-negative\n")) == (
        "labels line 2, column tags: suggestive-negative cannot be adult"
    )


def test_duplicate_file_names_the_later_line() -> None:
    assert str(error_of("a1.zz,zorbs,,no,,,\na1.zz,qwims,,no,,,\n")) == (
        "labels line 3, column file: duplicate file"
    )


def test_calibration_rows_are_left_out_of_the_gate_rows() -> None:
    result = parse(
        "a1.zz,zorbs,,no,,,\n"
        "b2.zz,zorbs,,yes,,,calibration-only\n"
        "c3.zz,qwims,,no,,,suggestive-negative\n"
        "d4.zz,qwims,,no,,,suggestive-negative;calibration-only\n"
    )
    assert [r.file for r in result.gate_rows()] == ["a1.zz", "c3.zz"]
    assert [r.file for r in result.suggestive_negatives()] == ["c3.zz"]
    assert [r.file for r in result.calibration_rows()] == ["b2.zz", "d4.zz"]


def test_repr_hides_planted_tags_and_values_after_full_validation() -> None:
    result = parse("QorvexFile.zz,zorbs,plinth,no,Zhyndel Ref,Zhyndel sub,suggestive-negative\n")
    for text in (repr(result.rows[0]), repr(result), str(result.rows[0])):
        for secret in ("QorvexFile", "Zhyndel", "plinth", "suggestive-negative"):
            assert secret not in text


def load(path: Path):
    return fl.load_labels(path, formats=FORMATS, topics=TOPICS)


def assert_fixed_unchained(error: fl.LabelsError, forbidden: str) -> None:
    assert forbidden not in str(error)
    assert error.__cause__ is None
    assert error.__context__ is None


def test_load_reads_a_regular_file_with_a_bom(tmp_path: Path) -> None:
    path = tmp_path / "labels-qorvex.csv"
    path.write_bytes(b"\xef\xbb\xbf" + (HEADER + "a1.zz,zorbs,,no,,,\n").encode())
    assert len(load(path).rows) == 1


def test_load_missing_file_is_fixed_text_without_the_path(tmp_path: Path) -> None:
    with pytest.raises(fl.LabelsError) as info:
        load(tmp_path / "qorvex-missing.csv")
    assert str(info.value) == "labels file: cannot read the labels file"
    assert_fixed_unchained(info.value, "qorvex")


def test_load_refuses_a_directory(tmp_path: Path) -> None:
    folder = tmp_path / "qorvex-dir"
    folder.mkdir()
    with pytest.raises(fl.LabelsError) as info:
        load(folder)
    assert str(info.value) == "labels file: the labels path is not a regular file"
    assert_fixed_unchained(info.value, "qorvex")


def test_load_path_with_a_nul_is_fixed_text() -> None:
    with pytest.raises(fl.LabelsError) as info:
        load(Path("qorvex" + chr(0) + ".csv"))
    assert str(info.value) == "labels file: cannot read the labels file"
    assert_fixed_unchained(info.value, "qorvex")


@pytest.mark.parametrize("payload", [b"\xff\xfe\x00bad", b"\xc3("])
def test_load_bad_encoding_is_fixed_text(tmp_path: Path, payload: bytes) -> None:
    path = tmp_path / "labels.csv"
    path.write_bytes(HEADER.encode() + b"a1.zz,zorbs,,no,," + payload + b",\n")
    with pytest.raises(fl.LabelsError) as info:
        load(path)
    assert str(info.value) == "labels file: the labels file is not valid UTF-8"
    assert_fixed_unchained(info.value, "zorbs")


def test_an_encoded_lone_surrogate_loads_and_is_never_quoted(tmp_path: Path) -> None:
    path = tmp_path / "labels.csv"
    path.write_bytes(HEADER.encode() + b"a1.zz,zorbs,,no,,\xed\xa0\x80,\n")
    assert len(load(path).rows) == 1
    path.write_bytes(HEADER.encode() + b"a1.zz,blorp\xed\xa0\x80,,no,,,\n")
    with pytest.raises(fl.LabelsError) as info:
        load(path)
    assert str(info.value) == "labels line 2, column format: not in the format vocabulary"
    assert_fixed_unchained(info.value, "blorp")
