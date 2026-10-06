"""Alembic environment (DB-001.1).

The DSN comes from `classifier.config.load_config` (`DB_DSN` wins; secrets never live in
`config.yaml`, CFG-001.D2). A caller that already holds a URL (the db tests) sets
`sqlalchemy.url` on the Alembic config and it is used as is. The URL is never logged.
"""

from alembic import context
from sqlalchemy import create_engine, pool

from classifier.config import load_config
from classifier.db.models import Base
from classifier.db.url import to_sqlalchemy_url

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    explicit = config.get_main_option("sqlalchemy.url")
    if explicit:
        return explicit
    dsn = load_config().db.dsn
    assert dsn is not None  # load_config refuses to return without one
    return to_sqlalchemy_url(dsn)


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    engine = create_engine(_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
