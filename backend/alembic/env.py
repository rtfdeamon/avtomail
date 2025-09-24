from __future__ import annotations

import asyncio
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.base import Base

# Interpret the config file for Python logging.
fileConfig(context.config.config_file_name)
configure_logging()

target_metadata = Base.metadata


def _sync_url(async_url: str) -> str:
    if async_url.startswith("postgresql+asyncpg://"):
        return async_url.replace("+asyncpg", "", 1)
    if async_url.startswith("sqlite+aiosqlite://"):
        return async_url.replace("+aiosqlite", "", 1)
    return async_url


def run_migrations_offline() -> None:
    settings = get_settings()
    url = _sync_url(settings.database_url)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    settings = get_settings()
    config = context.config.get_section(context.config.config_ini_section)
    assert config is not None
    config["sqlalchemy.url"] = _sync_url(settings.database_url)

    connectable = engine_from_config(
        config,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


def main() -> None:
    if context.is_offline_mode():
        run_migrations_offline()
    else:
        run_migrations_online()


main()
