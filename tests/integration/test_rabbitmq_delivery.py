import asyncio
import subprocess
import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from time import monotonic, sleep
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.infrastructure.llama_cpp import LlamaCpp
from bootstrap.main import create_app
from bootstrap.rabbitmq import open_exchange, open_topology
from bootstrap.settings import Settings
from outbox.application.ports.delivery import PendingEvent
from outbox.application.use_cases.publish_outbox import PublishOutbox
from outbox.infrastructure.postgres import PostgresOutboxStore
from outbox.infrastructure.rabbitmq import RabbitMQPublisher
from session.infrastructure.storage.database import build_engine
from storage.models import OutboxRow, ProcessedEventRow, SummaryRow


@pytest.fixture
def rabbit_settings(
    database_settings: Settings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Iterator[Settings]:
    monkeypatch.setenv("WORKER_METRICS_PATH", str(tmp_path / "worker-metrics.json"))
    monkeypatch.setenv("RABBITMQ_QUEUE", f"live-copilot.test.{uuid4().hex}")
    monkeypatch.setenv("OUTBOX_ENABLED", "true")
    settings = Settings()  # type: ignore[call-arg]
    yield settings

    async def cleanup() -> None:
        async with open_topology(settings) as (exchange, queue):
            channel = queue.channel
            await queue.delete(if_unused=False, if_empty=False)
            await exchange.delete(if_unused=False)
            dead_name = f"{settings.rabbitmq_queue}.dead"
            dead_queue = await channel.get_queue(dead_name, ensure=False)
            dead_exchange = await channel.get_exchange(dead_name, ensure=False)
            await dead_queue.delete(if_unused=False, if_empty=False)
            await dead_exchange.delete(if_unused=False)

    asyncio.run(cleanup())


@contextmanager
def running_worker() -> Iterator[None]:
    with subprocess.Popen([sys.executable, "-m", "worker"]) as process:
        try:
            yield
        finally:
            process.terminate()
            try:
                assert process.wait(timeout=8) == 0
            except subprocess.TimeoutExpired:
                process.kill()
                raise


def wait_for(condition: Callable[[], bool]) -> None:
    deadline = monotonic() + 12
    while not condition():
        if monotonic() >= deadline:
            pytest.fail("Condition did not become true within 12 seconds.")
        sleep(0.1)


def capture(
    client: TestClient, *, audio: bool, recommendation: bool = False
) -> tuple[str, list[UUID]]:
    session_id = client.post("/api/sessions").json()["session_id"]
    command = {"schema_version": 1, "session_id": session_id}
    ids = []
    with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
        socket.send_json({**command, "event_type": "capture.start"})
        assert socket.receive_json()["payload"]["status"] == "live"
        if audio:
            socket.send_bytes(b"\x01\x00" * 1600)
            assert socket.receive_json()["event_type"] == "transcript.interim"
        socket.send_json({**command, "event_type": "capture.stop"})
        assert socket.receive_json()["payload"]["status"] == "stopping"
        if audio:
            final = socket.receive_json()
            assert final["event_type"] == "transcript.final"
            ids.append(UUID(final["event_id"]))
        if recommendation:
            assert socket.receive_json()["event_type"] == "analysis.completed"
            proposed = socket.receive_json()
            assert proposed["event_type"] == "recommendation.created"
            ids.append(UUID(proposed["event_id"]))
        completed = socket.receive_json()
        assert completed["event_type"] == "session.completed"
        ids.append(UUID(completed["event_id"]))
    assert client.get(f"/api/sessions/{session_id}").json()["status"] == "completed"
    return session_id, ids


async def event_status(settings: Settings, ids: list[UUID]) -> tuple[int, int, int]:
    engine = build_engine(settings)
    try:
        async with async_sessionmaker(engine)() as db:
            rows = list(
                await db.scalars(select(OutboxRow).where(OutboxRow.event_id.in_(ids)))
            )
            processed = await db.scalar(
                select(func.count())
                .select_from(ProcessedEventRow)
                .where(ProcessedEventRow.event_id.in_(ids))
            )
            return (
                sum(row.published_at is None for row in rows),
                sum(row.attempts for row in rows),
                processed or 0,
            )
    finally:
        await engine.dispose()


async def queue_depth(settings: Settings, *, dead: bool = False) -> int:
    async with open_topology(settings) as (_, queue):
        if dead:
            queue = await queue.channel.get_queue(f"{queue.name}.dead", ensure=False)
        result = await queue.declare()
        assert result.message_count is not None
        return result.message_count


async def summary_count(settings: Settings, session_id: str) -> int:
    engine = build_engine(settings)
    try:
        async with async_sessionmaker(engine)() as db:
            count = await db.scalar(
                select(func.count())
                .select_from(SummaryRow)
                .filter_by(session_id=UUID(session_id))
            )
            return count or 0
    finally:
        await engine.dispose()


def test_broker_outage_and_worker_restart_preserve_live_capture(
    rabbit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fake_model(self: LlamaCpp, instructions: str, data: str) -> str:
        return '{"status":"insufficient_context"}'

    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr(LlamaCpp, "complete", fake_model)
    available = True

    def open_broker(settings: Settings):
        return open_exchange(
            settings if available else settings.model_copy(update={"rabbitmq_port": 1})
        )

    monkeypatch.setattr("bootstrap.main.open_exchange", open_broker)
    with running_worker(), TestClient(create_app()) as client:
        session_id, ids = capture(client, audio=True, recommendation=True)
        wait_for(lambda: asyncio.run(event_status(rabbit_settings, ids))[2] == 3)
        assert client.get(f"/api/sessions/{session_id}/report").json()["summary"] == (
            "Finalized utterances: 1. Recommendations: 1."
        )

    available = False
    with TestClient(create_app()) as client:
        session_id, ids = capture(client, audio=True, recommendation=True)
        wait_for(lambda: asyncio.run(event_status(rabbit_settings, ids))[1] >= 1)
        pending, _, processed = asyncio.run(event_status(rabbit_settings, ids))
        assert (pending, processed) == (3, 0)
        assert asyncio.run(summary_count(rabbit_settings, session_id)) == 0

        available = True
        wait_for(lambda: asyncio.run(queue_depth(rabbit_settings)) == 3)
        wait_for(lambda: asyncio.run(event_status(rabbit_settings, ids))[0] == 0)
        with running_worker():
            wait_for(lambda: asyncio.run(event_status(rabbit_settings, ids))[2] == 3)
            assert asyncio.run(summary_count(rabbit_settings, session_id)) == 1
        assert asyncio.run(queue_depth(rabbit_settings)) == 0


def test_confirmed_message_replays_after_publisher_exits_before_marking_database(
    rabbit_settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OUTBOX_ENABLED", "false")
    with TestClient(create_app()) as client:
        session_id, ids = capture(client, audio=False)

    class SimulatedExit(Exception):
        pass

    class ExitBeforeMark(PostgresOutboxStore):
        async def record_attempt(self, event_id: UUID, *, confirmed: bool) -> None:
            assert confirmed and event_id == ids[0]
            raise SimulatedExit

    async def publish_twice() -> None:
        engine = build_engine(rabbit_settings)
        factory = async_sessionmaker(engine)
        first = RabbitMQPublisher(lambda: open_exchange(rabbit_settings))
        restarted = RabbitMQPublisher(lambda: open_exchange(rabbit_settings))
        try:
            with pytest.raises(SimulatedExit):
                await PublishOutbox(ExitBeforeMark(factory), first).publish_batch()
            await first.close()
            assert await event_status(rabbit_settings, ids) == (1, 0, 0)
            assert await queue_depth(rabbit_settings) == 1
            assert (
                await PublishOutbox(
                    PostgresOutboxStore(factory), restarted
                ).publish_batch()
                == 1
            )
            assert await event_status(rabbit_settings, ids) == (0, 1, 0)
            assert await queue_depth(rabbit_settings) == 2
        finally:
            await first.close()
            await restarted.close()
            await engine.dispose()

    asyncio.run(publish_twice())
    with running_worker(), TestClient(create_app()) as client:
        wait_for(lambda: asyncio.run(event_status(rabbit_settings, ids))[2] == 1)
        wait_for(lambda: asyncio.run(queue_depth(rabbit_settings)) == 0)
        wait_for(
            lambda: 'worker_events_total{outcome="duplicate"} 1\n'
            in client.get("/metrics").text
        )
        assert (
            'worker_events_total{outcome="processed"} 1\n'
            in client.get("/metrics").text
        )
    assert asyncio.run(event_status(rabbit_settings, ids))[2] == 1
    assert asyncio.run(summary_count(rabbit_settings, session_id)) == 1


def test_invalid_and_exhausted_deliveries_reach_dead_letter_queue(
    rabbit_settings: Settings,
) -> None:
    event_id = uuid4()

    async def publish() -> None:
        publisher = RabbitMQPublisher(lambda: open_exchange(rabbit_settings))
        try:
            await publisher.publish(PendingEvent(uuid4(), "session.completed", {}))
            await publisher.publish(
                PendingEvent(
                    event_id,
                    "session.completed",
                    {
                        "schema_version": 1,
                        "event_id": str(event_id),
                        "event_type": "session.completed",
                        "session_id": str(uuid4()),
                    },
                )
            )
        finally:
            await publisher.close()

    asyncio.run(publish())
    with running_worker(), TestClient(create_app()) as client:
        wait_for(lambda: asyncio.run(queue_depth(rabbit_settings, dead=True)) == 2)
        assert asyncio.run(queue_depth(rabbit_settings)) == 0
        assert asyncio.run(event_status(rabbit_settings, [event_id]))[2] == 0
        metrics = client.get("/metrics").text
        assert 'worker_events_total{outcome="retried"} 2\n' in metrics
        assert 'worker_events_total{outcome="failed"} 2\n' in metrics
