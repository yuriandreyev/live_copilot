import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from bootstrap.settings import Settings
from session.infrastructure.storage.database import database_url


async def administer_database(settings: Settings, statement: str) -> None:
    url = database_url(settings).set(database="postgres")
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as conn:
            await conn.exec_driver_sql(statement)
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
def database_name() -> Iterator[str]:
    settings = Settings()  # type: ignore[call-arg]
    database = f"copilot_test_{uuid4().hex}"
    asyncio.run(administer_database(settings, f'CREATE DATABASE "{database}"'))
    try:
        env = {**os.environ, "POSTGRES_DB": database}
        alembic = [sys.executable, "-m", "alembic"]
        subprocess.run([*alembic, "upgrade", "head"], check=True, env=env)
        subprocess.run([*alembic, "upgrade", "head"], check=True, env=env)
        subprocess.run([*alembic, "check"], check=True, env=env)
        yield database
    finally:
        asyncio.run(administer_database(settings, f'DROP DATABASE "{database}"'))


@pytest.fixture
def database_settings(database_name: str, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("ASR_BACKEND", "fake")
    monkeypatch.setenv("LLM_ENABLED", "false")
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    monkeypatch.setenv("POSTGRES_DB", database_name)
    return Settings()  # type: ignore[call-arg]
