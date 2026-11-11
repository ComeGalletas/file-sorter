"""API-001.1.5: fixed, unchained errors (m3 checklist item 5; PR #224 round 1, items 1, 3, 5).

Each plant is first shown to be in the underlying library error, so the absence check could
have failed, and only then asserted absent from what the app raises.
"""

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError

from classifier.api.app import BAD_DSN, DB_UNAVAILABLE, INTERNAL_ERROR, guarded, read_only_engine
from classifier.api.views import ModelView

SECRET = "Zhyndel-planted-secret"


def _db_error() -> OperationalError:
    return OperationalError("select :p", {"p": SECRET}, Exception(f"server said {SECRET}"))


def _validation_error() -> ValidationError:
    try:
        ModelView(name=[SECRET], size_vram=1)  # type: ignore[arg-type]
    except ValidationError as exc:
        return exc
    raise AssertionError("ModelView accepted a list name")


def _raise(exc: Exception) -> None:
    raise exc


def test_the_plants_are_in_the_library_errors() -> None:
    assert SECRET in str(_db_error())
    assert SECRET in str(_validation_error())  # pydantic quotes input_value


@pytest.mark.parametrize(
    ("make", "code", "detail"),
    [
        (_db_error, 503, DB_UNAVAILABLE),
        (_validation_error, 500, INTERNAL_ERROR),
        (lambda: RuntimeError(SECRET), 500, INTERNAL_ERROR),
        (lambda: OSError(2, SECRET, f"/source/{SECRET}"), 500, INTERNAL_ERROR),
    ],
)
def test_guarded_raises_fixed_text_unchained(make, code, detail) -> None:
    exc = make()
    with pytest.raises(HTTPException) as caught:
        guarded(lambda: _raise(exc))
    err = caught.value
    assert (err.status_code, err.detail) == (code, detail)
    assert err.__cause__ is None
    assert err.__context__ is None
    assert SECRET not in str(err) and SECRET not in repr(err)


def test_guarded_returns_the_value() -> None:
    assert guarded(lambda: 7) == 7


def test_malformed_dsn_is_fixed_text_unchained() -> None:
    dsn = f"postgresql://qorvex:pw@127.0.0.1:{SECRET}/qorvex"
    with pytest.raises(ValueError) as raw:  # the plant is in SQLAlchemy's own error
        create_engine(dsn.replace("postgresql://", "postgresql+psycopg://"))
    assert SECRET in str(raw.value)
    with pytest.raises(ValueError) as caught:
        read_only_engine(dsn)
    assert str(caught.value) == BAD_DSN
    assert caught.value.__cause__ is None and caught.value.__context__ is None
