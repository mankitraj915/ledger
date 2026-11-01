import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, text

from app.config import normalize_database_url
from app.models import Base

config = context.config
if config.config_file_name is not None and config.attributes.get("configure_logging", True):
    fileConfig(config.config_file_name)

# Arbitrary constant: every instance that boots runs `alembic upgrade head`; the
# advisory lock makes concurrent boots migrate one at a time instead of racing.
MIGRATION_LOCK_ID = 7_301_955


def database_url() -> str:
    url = config.get_main_option("sqlalchemy.url") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Set DATABASE_URL to run migrations")
    return normalize_database_url(url)


def run_migrations_online() -> None:
    engine = create_engine(database_url())
    with engine.connect() as connection:
        # Session-level lock, taken outside the migration transaction so that a failed
        # migration rolls back cleanly and the unlock below still runs.
        connection.execute(text("SELECT pg_advisory_lock(:id)"), {"id": MIGRATION_LOCK_ID})
        connection.commit()
        try:
            context.configure(connection=connection, target_metadata=Base.metadata)
            with context.begin_transaction():
                context.run_migrations()
        finally:
            connection.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": MIGRATION_LOCK_ID})
            connection.commit()
    engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported")
run_migrations_online()
