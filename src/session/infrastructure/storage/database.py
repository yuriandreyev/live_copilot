from sqlalchemy import URL
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from bootstrap.settings import Settings


def database_url(settings: Settings) -> URL:
    return URL.create(
        "postgresql+asyncpg",
        username=settings.postgres_user,
        password=settings.postgres_password.get_secret_value(),
        host=settings.postgres_host,
        port=settings.postgres_port,
        database=settings.postgres_db,
    )


def build_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(database_url(settings), pool_pre_ping=True)
