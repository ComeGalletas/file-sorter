"""API-001.1.1: the read model's allowlist and repr hygiene (m3 item 4, m4 item 11)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from classifier.api.views import (
    ADULT_BRANCH,
    FILE_ROW_FIELDS,
    NOT_AVAILABLE,
    FileFilters,
    FileRow,
    GridCell,
    LoadedModelLike,
    file_row,
    is_adult,
    loaded_models_view,
)
from classifier.config import NsfwLevel
from classifier.db.models import FileStatus
from classifier.models.classify_rules import RULE_BRANCHES, branch_for_level

SECRET = "Qorvex-Zhyndel-secret"
HASH = "ab" * 32
NOW = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)


def _mapping(**over: object) -> dict[str, object]:
    m: dict[str, object] = {
        "source_hash": HASH,
        "short_hash": HASH[:8],
        "original_sanitized": SECRET,
        "ext": "png",
        "status": FileStatus.classified,
        "branch": "safe",
        "format": SECRET + "-format",
        "topic": SECRET + "-topic",
        "nsfw_level": "safe",
        "nsfw_traces": False,
        "needs_review": True,
        "review_reason": "nsfw_disagreement",
        "error": None,
        "updated_at": NOW,
    }
    m.update(over)
    return m


def test_file_row_fields_are_exactly_the_contract() -> None:
    assert tuple(FileRow.model_fields) == FILE_ROW_FIELDS
    assert len(FILE_ROW_FIELDS) == 16
    for banned in ("source_path", "duplicate_paths", "original_sanitized", "caption"):
        assert banned not in FileRow.model_fields


def test_file_row_refuses_extra_fields() -> None:
    data = file_row(_mapping()).model_dump()
    with pytest.raises(ValidationError):
        FileRow(**data, source_path="/source/x")


def test_file_row_from_mapping() -> None:
    row = file_row(_mapping())
    assert row.sanitized_name == SECRET + ".png"
    assert row.status == "classified"
    assert row.cross_check_disagrees is True
    assert file_row(_mapping(review_reason="unsorted")).cross_check_disagrees is False


def test_sanitized_name_is_null_before_sanitize() -> None:
    assert file_row(_mapping(original_sanitized=None)).sanitized_name is None


def test_reprs_hide_names() -> None:
    """The planted secret is held by each view (proved first), then absent from repr/str."""
    row = file_row(_mapping())
    cell = GridCell(topic=SECRET, format=SECRET, branch="safe", adult=False, count=1)
    filters = FileFilters(topic=SECRET, format=SECRET)
    assert SECRET in (row.sanitized_name or "") and SECRET in (row.topic or "")
    assert cell.topic == SECRET and filters.format == SECRET
    for view in (row, cell, filters):
        assert SECRET not in repr(view)
        assert SECRET not in str(view)
    assert HASH in repr(row)  # hashes stay visible


def test_adult_branch_is_the_classify_rules_adult_branch() -> None:
    """API-001.D8: pinned to the rules' own decision, so a renamed branch fails here."""
    for min_level in NsfwLevel:
        for level in NsfwLevel:
            branch = branch_for_level(level, min_level)
            assert is_adult(branch) is (level >= min_level)
            if level >= min_level:
                assert branch == ADULT_BRANCH
    assert ADULT_BRANCH in RULE_BRANCHES


@pytest.mark.parametrize(("branch", "adult"), [("nsfw", True), ("safe", False), (None, False)])
def test_is_adult(branch: str | None, adult: bool) -> None:
    assert is_adult(branch) is adult
    assert is_adult("adult") is False  # the old D8 wording is not a ledger value


@pytest.mark.parametrize(
    ("branch", "blurred"), [(ADULT_BRANCH, True), ("safe", False), (None, False)]
)
def test_blurred_comes_from_is_adult(branch: str | None, blurred: bool) -> None:
    """API-001.3 (API-001.D8): an adult row is blurred; safe and null rows are not."""
    assert file_row(_mapping(branch=branch)).blurred is blurred


class _Model:
    def __init__(self, name: str, size_vram: int) -> None:
        self.name = name
        self.size_vram = size_vram


class _Probe:
    def __init__(self, result: list[LoadedModelLike] | None | Exception) -> None:
        self.result = result

    def loaded_models(self) -> list[LoadedModelLike] | None:
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def test_loaded_models_view() -> None:
    assert loaded_models_view(None) == NOT_AVAILABLE
    assert loaded_models_view(_Probe(None)) == NOT_AVAILABLE
    assert loaded_models_view(_Probe(RuntimeError(SECRET))) == NOT_AVAILABLE
    assert loaded_models_view(_Probe([])) == []
    [model] = loaded_models_view(_Probe([_Model("qorvex-vlm:1b", 2048)]))  # type: ignore[misc]
    assert (model.name, model.size_vram) == ("qorvex-vlm:1b", 2048)
