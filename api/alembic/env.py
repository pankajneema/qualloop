"""Alembic environment. Runs as qualloop_owner (QL_DATABASE_URL_OWNER); tests may override sqlalchemy.url."""

import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import create_engine, pool

from alembic import context
from app.core.config import get_settings

# Revisions share `helpers.py` (RLS, STD columns, per-tenant data steps); make it importable from the CLI too.
sys.path.insert(0, str(Path(__file__).resolve().parent))

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)
# No ORM metadata yet: migrations are hand-written SQL/op calls (autogenerate unused at P00).
target_metadata = None


def _url() -> str:
    # str.replace guards against '%' interpolation in ConfigParser values
    override = config.get_main_option("sqlalchemy.url")
    return override.replace("%%", "%") if override else get_settings().database_url_owner


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


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
