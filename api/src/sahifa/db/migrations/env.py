"""Alembic environment: sync psycopg connection, models as autogenerate target."""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from sahifa.db import Base
from sahifa.db import models as _models  # noqa: F401  (registers every table on Base.metadata)
from sahifa.settings import Settings

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", Settings().migration_url.replace("%", "%%"))

target_metadata = Base.metadata

# Several api replicas may start at once; the advisory lock serialises their migrations.
MIGRATION_LOCK_KEY = 7_412_022_950_101


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    url = config.get_main_option("sqlalchemy.url") or ""
    # Alembic runs synchronously: psycopg 3 serves both modes under the same URL scheme.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        connection.exec_driver_sql("SELECT pg_advisory_lock(%s)", (MIGRATION_LOCK_KEY,))
        connection.commit()
        context.configure(connection=connection, target_metadata=target_metadata, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
