"""Database URL for SQLAlchemy and Alembic (DB-001.1, CFG-001.D2)."""

_PLAIN_SCHEMES = ("postgresql://", "postgres://")
_DRIVER = "postgresql+psycopg://"


def to_sqlalchemy_url(dsn: str) -> str:
    """Pin the psycopg 3 driver; the DSN in config and `DB_DSN` is a plain `postgresql://`."""
    for scheme in _PLAIN_SCHEMES:
        if dsn.startswith(scheme):
            return _DRIVER + dsn[len(scheme) :]
    return dsn
