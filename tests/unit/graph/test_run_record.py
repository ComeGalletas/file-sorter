"""PIPE-002.1: `flatten` and `error_code` give only what `runs` allows (DB-007.D3)."""

import re
from types import MappingProxyType

import pytest
import sqlalchemy.exc

from classifier.db.models import RUN_COUNT_FIELD, RUN_ERRORS
from classifier.graph import classify as classify_node
from classifier.graph import errors as graph_errors
from classifier.graph import sanitize as sanitize_node
from classifier.graph.classify import ClassifyConfigError, ClassifyResult
from classifier.graph.ingest import IngestResult
from classifier.graph.run_record import CODES, CountsShapeError, error_code, flatten
from classifier.graph.sanitize import SanitizeResult, WorkDirError
from classifier.models.classify_rules import ClassifyRulesError
from classifier.models.ollama import OllamaError
from classifier.models.vision import VisionError
from classifier.sanitize.rules import SanitizeConfigError

PLANT = "Qorvex"
FIELD = re.compile(RUN_COUNT_FIELD)


def test_the_codes_are_exactly_the_closed_set() -> None:
    assert set(CODES) == set(RUN_ERRORS) and len(CODES) == len(RUN_ERRORS)


def test_ingest_flattens_to_its_fields() -> None:
    assert flatten("ingest", IngestResult(new=2, skipped_known=1, duplicate=3)) == {
        "new": 2, "skipped_known": 1, "skipped_unreadable": 0, "duplicate": 3,
    }  # fmt: skip


def test_a_reason_map_flattens_to_errored_keys_without_the_node_prefix() -> None:
    result = ClassifyResult(
        classified=4, unsorted=1, errored=2,
        by_reason=MappingProxyType(
            {"classify_vlm_unanswered": 1, "classify_working_copy_unreadable": 1}
        ),
    )  # fmt: skip
    assert flatten("classify", result) == {
        "classified": 4, "unsorted": 1, "no_topic": 0, "adult": 0, "errored": 2,
        "errored_vlm_unanswered": 1, "errored_working_copy_unreadable": 1,
    }  # fmt: skip


@pytest.mark.parametrize(
    ("node", "reasons"),
    [
        ("sanitize", sanitize_node.REASONS),
        ("classify", tuple(r for r in graph_errors._REASONS if r.startswith("classify_"))),
    ],
)
def test_every_registered_reason_gives_a_key_runs_counts_accepts(
    node: str, reasons: tuple[str, ...]
) -> None:
    assert reasons  # the registry is populated by importing the nodes
    kind = SanitizeResult if node == "sanitize" else ClassifyResult
    result = kind(errored=len(reasons), by_reason=MappingProxyType(dict.fromkeys(reasons, 1)))
    keys = flatten(node, result)
    assert all(FIELD.fullmatch(key) for key in keys)
    assert len(keys) == len(kind.__dataclass_fields__) - 1 + len(reasons)


def test_none_and_a_bare_number() -> None:
    assert flatten("caption", None) == {}
    assert flatten("ingest", 3) == {"count": 3}
    assert flatten("ingest", 1.5) == {"count": 1.5}


@pytest.mark.parametrize(
    "result",
    [
        {f"/source/{PLANT}.png": 1},  # a path as a key
        {"new": f"{PLANT}.png"},  # text as a value
        {"new": True},  # a flag is not a count
        {"new": [1]},
        {"by_reason": {f"sanitize_{PLANT} trip": 1}},  # a reason that isn't a field name
        {"by_reason": {"sanitize_name_failed": "1"}},
        {"details": {"x": 1}},  # an unknown nested map
        f"/source/{PLANT}.png",
        True,
        [1, 2],
    ],
)
def test_a_result_runs_counts_cannot_hold_is_refused_with_fixed_text(result: object) -> None:
    with pytest.raises(CountsShapeError) as caught:
        flatten("sanitize", result)
    assert PLANT not in str(caught.value)
    assert "sanitize" in str(caught.value)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (KeyboardInterrupt(), "interrupted"),
        (SanitizeConfigError.__new__(SanitizeConfigError), "sanitize_config"),
        (WorkDirError.__new__(WorkDirError), "work_dir"),
        (ClassifyConfigError(PLANT), "classify_config"),
        (ClassifyRulesError.__new__(ClassifyRulesError), "classify_rules"),
        (VisionError.__new__(VisionError), "vision"),
        (OllamaError.__new__(OllamaError), "ollama"),
        # A psycopg error is the db tier's (tests/db/graph/test_run_record.py, tier audit).
        (sqlalchemy.exc.OperationalError("select", {}, Exception(PLANT)), "database"),
        (RuntimeError(PLANT), "internal"),
        (CountsShapeError(PLANT), "internal"),
        (SystemExit(1), "internal"),
    ],
)
def test_error_code_maps_each_class_to_a_fixed_code(error: BaseException, code: str) -> None:
    assert error_code(error) == code
    assert code in RUN_ERRORS


def test_the_nodes_import_their_reasons_through_the_registry() -> None:
    # The parametrisation above reads graph_errors._REASONS; classify registers its own.
    assert classify_node.VLM_UNANSWERED in graph_errors._REASONS
