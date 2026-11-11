"""What a run writes to `runs` (PIPE-002.1; R-API-6, DB-007.D3).

`flatten` turns one node's result into `{field: number}`, the inner shape `runs.counts`
allows. `error_code` maps what ended a run to one of the fixed `runs.error` codes. Neither
ever carries a path, a name or an exception's text.
"""

import dataclasses
import re
from collections.abc import Mapping

import psycopg
import sqlalchemy.exc

from classifier.db.models import RUN_COUNT_FIELD
from classifier.graph.classify import ClassifyConfigError
from classifier.graph.sanitize import WorkDirError
from classifier.models.classify_rules import ClassifyRulesError
from classifier.models.ollama import OllamaError
from classifier.models.vision import VisionError
from classifier.sanitize.rules import SanitizeConfigError

_FIELD = re.compile(RUN_COUNT_FIELD)
# A reason map breaks the `errored` count down (SanitizeResult, ClassifyResult), so its keys
# are `errored_<reason>`, with the node's own prefix dropped from the fixed reason
# (`classify_vlm_unanswered` -> `errored_vlm_unanswered`). `by_reason_<reason>` would not
# fit runs_counts_fields' 32 characters.
_REASON_MAPS = {"by_reason": "errored"}


class CountsShapeError(Exception):
    """A node result that `runs.counts` can't hold. Fixed text: names the node only."""


def flatten(node: str, result: object) -> dict[str, int | float]:
    """One node's result as `{field: number}` (DB-007.D3).

    None is an empty object, and a bare number is `{"count": n}` (a node's result is typed
    `object`, so a stand-in may return just a count).
    """
    if result is None:
        return {}
    if isinstance(result, int | float) and not isinstance(result, bool):
        return {"count": result}
    if dataclasses.is_dataclass(result) and not isinstance(result, type):
        items = {f.name: getattr(result, f.name) for f in dataclasses.fields(result)}
    elif isinstance(result, Mapping):
        items = dict(result)
    else:
        raise CountsShapeError(f"node {node} returned a result runs.counts can't hold")
    out: dict[str, int | float] = {}
    for key, value in items.items():
        if isinstance(value, Mapping) and key in _REASON_MAPS:
            for reason, count in value.items():
                _put(out, node, f"{_REASON_MAPS[key]}_{_strip(node, reason)}", count)
        else:
            _put(out, node, key, value)
    return out


def _strip(node: str, reason: object) -> str:
    text = str(reason)
    return text.removeprefix(f"{node}_")


def _put(out: dict[str, int | float], node: str, key: object, value: object) -> None:
    # bool is an int subclass; a flag is not a count.
    ok_value = isinstance(value, int | float) and not isinstance(value, bool)
    if not (isinstance(key, str) and _FIELD.fullmatch(key) and ok_value):
        raise CountsShapeError(f"node {node} returned a count runs.counts can't hold")
    out[key] = value


# Checked in order; the first match wins. Each code is in RUN_ERRORS (DB-007.D3).
_CODES: tuple[tuple[type[BaseException] | tuple[type[BaseException], ...], str], ...] = (
    (KeyboardInterrupt, "interrupted"),
    (SanitizeConfigError, "sanitize_config"),
    (WorkDirError, "work_dir"),
    (ClassifyConfigError, "classify_config"),
    (ClassifyRulesError, "classify_rules"),
    (VisionError, "vision"),
    (OllamaError, "ollama"),
    ((psycopg.Error, sqlalchemy.exc.SQLAlchemyError), "database"),
)
FALLBACK = "internal"
CODES = tuple(code for _, code in _CODES) + (FALLBACK,)  # the tests pin CODES == RUN_ERRORS


def error_code(error: BaseException) -> str:
    """The fixed `runs.error` code for what ended a run; `internal` for anything else."""
    for kinds, code in _CODES:
        if isinstance(error, kinds):
            return code
    return FALLBACK
