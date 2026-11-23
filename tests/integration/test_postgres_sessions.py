import asyncio
from dataclasses import replace
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

import workflows.live_capture.workflow as capture_workflow
from agents.infrastructure.llama_cpp import LlamaCpp
from bootstrap.main import create_app
from bootstrap.settings import Settings
from session.domain.session import Session
from session.infrastructure.storage.capture_records import PostgresCaptureRecordStore
from session.infrastructure.storage.database import build_engine
from session.infrastructure.storage.sessions import PostgresSessionRepository
from session.public import OutboxEvent, StoredRecommendation
from storage.schema import (
    outbox_events,
    recommendations,
    session_summaries,
    sessions,
    utterances,
)
from transcription.infrastructure.audio.fake_asr import FakeSpeechRecognizer
from transcription.public import FinalizedUtterance


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
            assert client.get(f"{url}/transcript").json()["utterances"] == []

            socket.send_json({**envelope, "event_type": "capture.stop"})
            assert socket.receive_json()["payload"]["status"] == "stopping"
            final = socket.receive_json()
            assert final["event_type"] == "transcript.final"
            assert socket.receive_json()["event_type"] == "session.completed"

        details = client.get(url).json()
        assert details["status"] == "completed"
        assert details["ended_at"] is not None
        assert client.get(f"{url}/transcript").json()["utterances"] == [
            {**final["payload"], "sequence": final["sequence"], "recommendations": []}
        ]

        interrupted = client.post("/api/sessions").json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{interrupted}") as socket:
            socket.send_json(
                {**envelope, "session_id": interrupted, "event_type": "capture.start"}
            )
            assert socket.receive_json()["payload"]["status"] == "live"

        details = client.get(f"/api/sessions/{interrupted}").json()
        assert details["status"] == "interrupted"
        assert details["ended_at"] is not None


class DuplicateRecognizer(FakeSpeechRecognizer):
    def __init__(self) -> None:
        super().__init__()
        self.final = FinalizedUtterance(
            utterance_id=uuid4(),
            start_ms=0,
            end_ms=100,
            text="We are receiving duplicate API notifications.",
        )

    async def accept_frame(self, frame: bytes) -> FinalizedUtterance:
        return self.final

    async def finish(self) -> FinalizedUtterance:
        return self.final


def configure_recommendations(monkeypatch: pytest.MonkeyPatch) -> None:
    async def complete(self: LlamaCpp, instructions: str, data: str) -> str:
        if '"transcript"' in data:
            return (
                '{"status":"identified","issue":"Duplicate notifications",'
                '"intent":"Find the cause","confidence":0.95}'
            )
        return (
            '{"action":"Сравните идентификаторы событий.","rationale":"При повторной доставке идентификаторы могут совпадать.",'
            '"faq_ids":["duplicate-notifications"]}'
        )

    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr("bootstrap.main.FakeSpeechRecognizer", DuplicateRecognizer)
    monkeypatch.setattr(LlamaCpp, "complete", complete)


def test_live_records_and_outbox_match_websocket_after_replay(
    database_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_recommendations(monkeypatch)

    with TestClient(create_app()) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        url = f"/api/sessions/{session_id}"
        command = {"schema_version": 1, "session_id": session_id}
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_json({**command, "event_type": "capture.start"})
            assert socket.receive_json()["payload"]["status"] == "live"
            socket.send_bytes(b"\x01\x00")
            final = socket.receive_json()
            assert final["event_type"] == "transcript.final"
            assert (
                client.get(f"{url}/transcript").json()["utterances"][0]["text"]
                == (final["payload"]["text"])
            )

            assert socket.receive_json()["event_type"] == "analysis.completed"
            recommendation = socket.receive_json()
            assert recommendation["event_type"] == "recommendation.created"
            assert recommendation["payload"]["faq_ids"] == ["duplicate-notifications"]

            # Stop replays the same final utterance from the recognizer's flush.
            socket.send_json({**command, "event_type": "capture.stop"})
            assert socket.receive_json()["payload"]["status"] == "stopping"
            completion = socket.receive_json()
            assert completion["event_type"] == "session.completed"

        async def replay_recommendation_and_check_outbox() -> None:
            engine = build_engine(database_settings)
            factory = async_sessionmaker(engine)
            try:
                payload = recommendation["payload"]
                event = OutboxEvent(
                    UUID(recommendation["event_id"]),
                    recommendation["event_type"],
                    recommendation,
                )
                inserted = await PostgresCaptureRecordStore(
                    factory
                ).record_recommendation(
                    UUID(session_id),
                    UUID(payload["utterance_id"]),
                    StoredRecommendation(
                        UUID(payload["recommendation_id"]),
                        payload["context_version"],
                        payload["action"],
                        payload["rationale"],
                        tuple(payload["faq_ids"]),
                        payload["prompt_version"],
                    ),
                    event,
                )
                assert inserted is False
                async with factory() as db:
                    rows = (
                        await db.execute(
                            sa.select(outbox_events).where(
                                outbox_events.c.payload["session_id"].astext
                                == session_id
                            )
                        )
                    ).all()
                    assert {str(row.event_id): row.payload for row in rows} == {
                        event["event_id"]: event
                        for event in (final, recommendation, completion)
                    }
                    assert sorted(row.type for row in rows) == [
                        "recommendation.created",
                        "session.completed",
                        "transcript.final",
                    ]
                    assert all(row.published_at is None for row in rows)
            finally:
                await engine.dispose()

        asyncio.run(replay_recommendation_and_check_outbox())
        stored_recommendation = dict(recommendation["payload"])
        assert (
            stored_recommendation.pop("utterance_id")
            == final["payload"]["utterance_id"]
        )
        assert client.get(f"{url}/transcript").json()["utterances"] == [
            {
                **final["payload"],
                "sequence": final["sequence"],
                "recommendations": [stored_recommendation],
            }
        ]


@pytest.mark.parametrize(
    "failed_type", ["transcript.final", "recommendation.created", "session.completed"]
)
def test_outbox_failure_rolls_back_record_and_emits_persistence_error(
    database_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    failed_type: str,
) -> None:
    if failed_type != "session.completed":
        configure_recommendations(monkeypatch)
    occupied_id = uuid4()

    async def seed_outbox_id() -> None:
        engine = build_engine(database_settings)
        try:
            async with engine.begin() as conn:
                await conn.execute(
                    outbox_events.insert().values(
                        event_id=occupied_id,
                        type="test",
                        payload={},
                    )
                )
        finally:
            await engine.dispose()

    asyncio.run(seed_outbox_id())
    original = capture_workflow._outbox_event

    def collide(
        event: capture_workflow.TranscriptFinal
        | capture_workflow.RecommendationCreated
        | capture_workflow.SessionCompleted,
    ) -> OutboxEvent:
        outbox = original(event)
        return (
            replace(outbox, event_id=occupied_id)
            if event.event_type == failed_type
            else outbox
        )

    monkeypatch.setattr(capture_workflow, "_outbox_event", collide)
    with TestClient(create_app()) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        url = f"/api/sessions/{session_id}"
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_json(
                {
                    "schema_version": 1,
                    "session_id": session_id,
                    "event_type": "capture.start",
                }
            )
            assert socket.receive_json()["payload"]["status"] == "live"
            if failed_type == "session.completed":
                socket.send_json(
                    {
                        "schema_version": 1,
                        "session_id": session_id,
                        "event_type": "capture.stop",
                    }
                )
                assert socket.receive_json()["payload"]["status"] == "stopping"
            else:
                socket.send_bytes(b"\x01\x00")
            if failed_type == "recommendation.created":
                assert socket.receive_json()["event_type"] == "transcript.final"
            error = socket.receive_json()
            assert error["event_type"] == "session.error"
            assert error["payload"]["code"] == "persistence_failed"

        rows = client.get(f"{url}/transcript").json()["utterances"]
        if failed_type == "recommendation.created":
            assert len(rows) == 1 and rows[0]["recommendations"] == []
        else:
            assert rows == []
        assert client.get(url).json()["status"] == "failed"
