"""Alembic environment — async (asyncpg). Pulls the URL and metadata from the
app so migrations and the app never drift apart."""
import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config import get_settings
from app.models import Base  # importing the package registers every model

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Inject the real database URL from Settings (asyncpg driver).
config.set_main_option("sqlalchemy.url", get_settings().DATABASE_URL)

target_metadata = Base.metadata


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    # The HNSW embedding index is created by raw SQL in the migration; pgvector
    # access methods don't round-trip through autogenerate, so we manage it by
    # hand and tell autogenerate to ignore it (keeps `alembic check` honest).
    if type_ == "index" and name == "ix_knowledge_chunks_embedding":
        return False
    return True


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_offline() -> None:
    context.configure(
        url=get_settings().DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
