"""DB-001.1.1: the DSN is turned into a psycopg 3 SQLAlchemy URL, and nothing else changes."""

import pytest

from classifier.db.url import to_sqlalchemy_url


@pytest.mark.parametrize("scheme", ["postgresql", "postgres"])
def test_plain_scheme_gets_the_psycopg_driver(scheme: str) -> None:
    assert (
        to_sqlalchemy_url(f"{scheme}://u:p@host:5432/db") == "postgresql+psycopg://u:p@host:5432/db"
    )


def test_url_with_a_driver_is_left_alone() -> None:
    url = "postgresql+psycopg://u:p@host/db?options=-c%20search_path%3Dx"
    assert to_sqlalchemy_url(url) == url
