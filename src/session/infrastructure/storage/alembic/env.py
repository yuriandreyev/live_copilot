import asyncio
import logging

from alembic import context
from sqlalchemy.engine import Connection

from bootstrap.settings import Settings
from session.infrastructure.storage.database import build_engine, database_url
from storage.schema import metadata


def migrate(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=metadata)
    with context.begin_transaction():
        context.run_migrations()


async def migrate_online(settings: Settings) -> None:
    engine = build_engine(settings)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


logging.basicConfig(level=logging.INFO, format="%(levelname)s [%(name)s] %(message)s")
settings = Settings()  # type: ignore[call-arg]
if context.is_offline_mode():
    context.configure(
        url=database_url(settings), target_metadata=metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(migrate_online(settings))
