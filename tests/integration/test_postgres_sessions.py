import asyncio
import os
import subprocess
import sys
from collections.abc import Iterator
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from bootstrap.main import create_app
from bootstrap.settings import Settings
from session.domain.session import Session
from session.infrastructure.storage.database import build_engine, database_url
from session.infrastructure.storage.schema import (
    outbox_events,
    recommendations,
    session_summaries,
    sessions,
    utterances,
)
from session.infrastructure.storage.sessions import PostgresSessionRepository


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
    monkeypatch.setenv("POSTGRES_DB", database_name)
    return Settings()  # type: ignore[call-arg]


def test_clean_database_is_at_migration_head(database_settings: Settings) -> None:
    async def check() -> None:
        engine = build_engine(database_settings)
        try:
            async with engine.connect() as conn:
                revisions = await conn.execute(
                    sa.text("SELECT version_num FROM alembic_version")
                )
                assert revisions.scalars().all() == ["0001"]
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_session_http_lifecycle_and_persisted_reads(
    database_settings: Settings,
) -> None:
    first_utterance, second_utterance = uuid4(), uuid4()

    async def seed(session_id: UUID) -> None:
        engine = build_engine(database_settings)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    utterances.insert(),
                    [
                        dict(
                            id=second_utterance,
                            session_id=session_id,
                            sequence=9,
                            start_ms=100,
                            end_ms=200,
                            text="Second",
                        ),
                        dict(
                            id=first_utterance,
                            session_id=session_id,
                            sequence=3,
                            start_ms=0,
                            end_ms=100,
                            text="First",
                        ),
                    ],
                )
                await conn.execute(
                    recommendations.insert(),
                    [
                        dict(
                            id=uuid4(),
                            session_id=session_id,
                            utterance_id=first_utterance,
                            context_version=version,
                            action="Check retries",
                            rationale="Repeated events",
                            faq_ids=["idempotency"],
                            prompt_version="1",
                        )
                        for version in (2, 1)
                    ],
                )
                await conn.execute(
                    session_summaries.insert().values(
                        session_id=session_id, summary="Retry report"
                    )
                )
        finally:
            await engine.dispose()

    with TestClient(create_app()) as client:
        created = client.post("/api/sessions")
        assert created.status_code == 201
        assert created.json()["status"] == "created"
        session_id = UUID(created.json()["session_id"])
        assert session_id.version == 4
        url = f"/api/sessions/{session_id}"

        details = client.get(url)
        assert details.status_code == 200
        assert details.json()["status"] == "created"
        assert details.json()["started_at"] is None
        assert details.json()["ended_at"] is None
        assert details.json()["summary_available"] is False
        assert client.get(f"{url}/transcript").json()["utterances"] == []
        assert client.get(f"{url}/report").json()["summary"] is None

        asyncio.run(seed(session_id))

        transcript = client.get(f"{url}/transcript")
        assert transcript.status_code == 200
        first, second = transcript.json()["utterances"]
        assert [first["sequence"], second["sequence"]] == [3, 9]
        assert first["utterance_id"] == str(first_utterance)
        assert [item["context_version"] for item in first["recommendations"]] == [1, 2]
        assert first["recommendations"][0]["faq_ids"] == ["idempotency"]
        assert second["recommendations"] == []
        assert client.get(url).json()["summary_available"] is True
        assert client.get(f"{url}/report").json()["summary"] == "Retry report"

        unknown = f"/api/sessions/{uuid4()}"
        for suffix in ("", "/transcript", "/report"):
            assert client.get(f"{unknown}{suffix}").status_code == 404
        assert client.get("/api/sessions/invalid").status_code == 422


def test_concurrent_transactions_use_distinct_sessions_and_connections(
    database_settings: Settings,
) -> None:
    async def check() -> None:
        engine = build_engine(database_settings)
        factory = async_sessionmaker(engine)
        first_ready, second_ready = asyncio.Event(), asyncio.Event()

        async def transaction(ready: asyncio.Event, peer_ready: asyncio.Event):
            async with factory.begin() as db:
                pid = await db.scalar(sa.func.pg_backend_pid().select())
                ready.set()
                await asyncio.wait_for(peer_ready.wait(), timeout=5)
                return db, pid

        try:
            first, second = await asyncio.gather(
                transaction(first_ready, second_ready),
                transaction(second_ready, first_ready),
            )
            assert first[0] is not second[0]
            assert first[1] != second[1]
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_duplicate_sequence_rolls_back_entire_failed_transaction(
    database_settings: Settings,
) -> None:
    async def check() -> None:
        engine = build_engine(database_settings)
        factory = async_sessionmaker(engine)
        session = Session()
        event_id = uuid4()
        original = dict(
            session_id=session.id, sequence=1, start_ms=0, end_ms=10, text="Original"
        )
        try:
            await PostgresSessionRepository(factory).create(session)
            async with factory.begin() as db:
                await db.execute(utterances.insert().values(id=uuid4(), **original))

            with pytest.raises(IntegrityError, match="uq_utterances_session_sequence"):
                async with factory.begin() as db:
                    await db.execute(
                        outbox_events.insert().values(
                            event_id=event_id, type="transcript.final", payload={}
                        )
                    )
                    await db.execute(utterances.insert().values(id=uuid4(), **original))

            async with factory() as db:
                assert (
                    await db.scalar(
                        sa.select(sa.func.count())
                        .select_from(utterances)
                        .where(utterances.c.session_id == session.id)
                    )
                    == 1
                )
                assert (
                    await db.scalar(
                        sa.select(outbox_events.c.event_id).where(
                            outbox_events.c.event_id == event_id
                        )
                    )
                    is None
                )
                assert await db.scalar(
                    sa.select(sessions.c.id).where(sessions.c.id == session.id)
                )
        finally:
            await engine.dispose()

    asyncio.run(check())


def test_websocket_updates_persisted_session_state(database_settings: Settings) -> None:
    with TestClient(create_app()) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        url = f"/api/sessions/{session_id}"
        envelope = {"schema_version": 1, "session_id": session_id}

        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_json({**envelope, "event_type": "capture.start"})
            assert socket.receive_json()["payload"]["status"] == "live"
            details = client.get(url).json()
            assert details["status"] == "live"
            assert details["started_at"] is not None
            assert details["ended_at"] is None

            socket.send_bytes(b"\x01\x00" * 1600)
            interim = socket.receive_json()
            assert interim["event_type"] == "transcript.interim"
            assert interim["payload"]["end_ms"] == 100

            socket.send_json({**envelope, "event_type": "capture.stop"})
            assert socket.receive_json()["payload"]["status"] == "stopping"
            assert socket.receive_json()["event_type"] == "transcript.final"
            assert socket.receive_json()["event_type"] == "session.completed"

        details = client.get(url).json()
        assert details["status"] == "completed"
        assert details["ended_at"] is not None
        assert client.get(f"{url}/transcript").json()["utterances"] == []

        interrupted = client.post("/api/sessions").json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{interrupted}") as socket:
            socket.send_json(
                {**envelope, "session_id": interrupted, "event_type": "capture.start"}
            )
            assert socket.receive_json()["payload"]["status"] == "live"

        details = client.get(f"/api/sessions/{interrupted}").json()
        assert details["status"] == "interrupted"
        assert details["ended_at"] is not None
