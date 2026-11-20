import asyncio
from datetime import UTC, datetime
from threading import Event
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient, WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from bootstrap.health import router as health_router
from copilot_contracts.events import TranscriptWindow
from session.application.ports import SessionDetails
from session.domain.enums import SessionStatus
from session.presentation.websocket import MAX_FRAME_BYTES, websocket_routes
from session.public import SessionLifecycle
from transcription.infrastructure.audio.fake_asr import FakeSpeechRecognizer
from workflows.live_capture.workflow import LiveCapture

FRAME_1 = b"\x01\x00" * 1600
FRAME_2 = b"\xff\xff" * 1600


class MemorySessionStore:
    def __init__(self) -> None:
        self.statuses: dict[UUID, SessionStatus] = {}

    def create(self) -> UUID:
        session_id = uuid4()
        self.statuses[session_id] = SessionStatus.CREATED
        return session_id

    async def get(self, session_id: UUID) -> SessionDetails | None:
        status = self.statuses.get(session_id)
        if status is None:
            return None
        return SessionDetails(session_id, status, datetime.now(UTC), None, None, False)

    async def transition(
        self, session_id: UUID, previous: SessionStatus, target: SessionStatus
    ) -> bool:
        if self.statuses[session_id] is not previous:
            return False
        self.statuses[session_id] = target
        return True


class RecordingRecognizer(FakeSpeechRecognizer):
    def __init__(self) -> None:
        super().__init__()
        self.frames: list[bytes] = []

    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None:
        self.frames.append(frame)
        return await super().accept_frame(frame)


class SlowRecognizer(RecordingRecognizer):
    def __init__(self) -> None:
        super().__init__()
        self.started = Event()
        self.cancelled = Event()

    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None:
        self.frames.append(frame)
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cancelled.set()
        return None


def make_client(
    store: MemorySessionStore,
    recognizer: FakeSpeechRecognizer,
    *,
    audio_capacity: int = 30,
    flush_timeout: float = 5,
) -> TestClient:
    app = FastAPI()
    app.include_router(health_router)
    app.include_router(
        websocket_routes(
            LiveCapture(
                SessionLifecycle(store),
                lambda: recognizer,
                audio_capacity=audio_capacity,
                flush_timeout=flush_timeout,
            )
        )
    )
    return TestClient(app)


def command(socket: WebSocketTestSession, session_id: UUID, name: str) -> None:
    socket.send_json(
        {"schema_version": 1, "event_type": name, "session_id": str(session_id)}
    )


def start(socket: WebSocketTestSession, session_id: UUID) -> None:
    command(socket, session_id, "capture.start")
    assert socket.receive_json()["payload"] == {"status": "live"}


def assert_close(socket: WebSocketTestSession, code: int) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:
        socket.receive_json()
    assert closed.value.code == code


def test_capture_drains_frames_in_order_then_finalizes() -> None:
    store = MemorySessionStore()
    session_id = store.create()
    recognizer = RecordingRecognizer()

    with make_client(store, recognizer) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            start(socket, session_id)
            socket.send_bytes(FRAME_1)
            socket.send_bytes(FRAME_2)
            command(socket, session_id, "capture.stop")
            events = [socket.receive_json() for _ in range(5)]
            assert_close(socket, 1000)

    assert recognizer.frames == [FRAME_1, FRAME_2]
    assert [event["sequence"] for event in events] == [2, 3, 4, 5, 6]
    assert [
        e["payload"]["end_ms"]
        for e in events
        if e["event_type"] == "transcript.interim"
    ] == [100, 200]
    assert {"status": "stopping"} in [event["payload"] for event in events[:3]]
    assert events[-2]["event_type"] == "transcript.final"
    assert events[-2]["payload"]["end_ms"] == 200
    UUID(events[-2]["payload"]["utterance_id"])
    assert events[-1]["event_type"] == "session.completed"
    assert store.statuses[session_id] is SessionStatus.COMPLETED


@pytest.mark.parametrize("frame", [b"", b"\x00", b"\x00" * (MAX_FRAME_BYTES + 2)])
def test_invalid_audio_returns_visible_error(frame: bytes) -> None:
    store = MemorySessionStore()
    session_id = store.create()
    with make_client(store, FakeSpeechRecognizer()) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            start(socket, session_id)
            socket.send_bytes(frame)
            assert socket.receive_json()["payload"]["code"] == "invalid_audio"
            assert_close(socket, 1008)
    assert store.statuses[session_id] is SessionStatus.FAILED


@pytest.mark.parametrize(
    "value", ["{", '{"schema_version":2,"event_type":"capture.start"}']
)
def test_malformed_command_leaves_session_available(value: str) -> None:
    store = MemorySessionStore()
    session_id = store.create()
    with make_client(store, FakeSpeechRecognizer()) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_text(value)
            assert socket.receive_json()["payload"]["code"] == "invalid_command"
            assert_close(socket, 1008)
    assert store.statuses[session_id] is SessionStatus.CREATED


@pytest.mark.parametrize("active", [False, True])
def test_command_for_another_session_is_rejected(active: bool) -> None:
    store = MemorySessionStore()
    session_id = store.create()
    other_session_id = store.create()
    with make_client(store, FakeSpeechRecognizer()) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            if active:
                start(socket, session_id)
            command(
                socket,
                other_session_id,
                "capture.stop" if active else "capture.start",
            )
            assert socket.receive_json()["payload"]["code"] == "invalid_command"
            assert_close(socket, 1008)
    assert store.statuses[session_id] is (
        SessionStatus.FAILED if active else SessionStatus.CREATED
    )
    assert store.statuses[other_session_id] is SessionStatus.CREATED


def test_stop_before_start_is_rejected() -> None:
    store = MemorySessionStore()
    session_id = store.create()
    with make_client(store, FakeSpeechRecognizer()) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            command(socket, session_id, "capture.stop")
            assert socket.receive_json()["payload"]["code"] == "command_order"
            assert_close(socket, 1008)
    assert store.statuses[session_id] is SessionStatus.CREATED


def test_unknown_session_has_explicit_error() -> None:
    with make_client(MemorySessionStore(), FakeSpeechRecognizer()) as client:
        with client.websocket_connect(f"/ws/sessions/{uuid4()}") as socket:
            assert socket.receive_json()["payload"]["code"] == "unknown_session"
            assert_close(socket, 1008)


def test_second_capture_is_rejected_and_disconnect_releases_slot() -> None:
    store = MemorySessionStore()
    first, second = store.create(), store.create()
    with make_client(store, FakeSpeechRecognizer()) as client:
        with client.websocket_connect(f"/ws/sessions/{first}") as socket:
            start(socket, first)
            with client.websocket_connect(f"/ws/sessions/{second}") as competing:
                command(competing, second, "capture.start")
                assert competing.receive_json()["payload"]["code"] == "session_busy"
                assert_close(competing, 1013)
            assert client.get("/healthz").status_code == 200
        assert store.statuses[first] is SessionStatus.INTERRUPTED
        with client.websocket_connect(f"/ws/sessions/{second}") as socket:
            start(socket, second)


def test_slow_recognizer_stays_responsive_and_queue_overload_is_visible() -> None:
    store = MemorySessionStore()
    session_id = store.create()
    recognizer = SlowRecognizer()

    with make_client(store, recognizer, audio_capacity=1) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            start(socket, session_id)
            socket.send_bytes(FRAME_1)
            assert recognizer.started.wait(timeout=2)
            assert client.get("/healthz").status_code == 200

            socket.send_bytes(FRAME_2)
            socket.send_bytes(FRAME_2)
            event = socket.receive_json()
            assert event["event_type"] == "session.overloaded"
            assert event["payload"]["code"] == "audio_overload"
            assert_close(socket, 1013)

    assert recognizer.frames == [FRAME_1]
    assert recognizer.cancelled.is_set()
    assert store.statuses[session_id] is SessionStatus.FAILED


def test_stop_flush_is_bounded_for_slow_recognizer() -> None:
    store = MemorySessionStore()
    session_id = store.create()
    recognizer = SlowRecognizer()

    with make_client(store, recognizer, flush_timeout=0.2) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            start(socket, session_id)
            socket.send_bytes(FRAME_1)
            assert recognizer.started.wait(timeout=2)
            command(socket, session_id, "capture.stop")
            assert socket.receive_json()["payload"] == {"status": "stopping"}
            assert socket.receive_json()["payload"]["code"] == "flush_timeout"
            assert_close(socket, 1011)

    assert recognizer.cancelled.is_set()
    assert store.statuses[session_id] is SessionStatus.FAILED


def test_disconnect_during_flush_interrupts_session() -> None:
    store = MemorySessionStore()
    session_id = store.create()
    recognizer = SlowRecognizer()

    with make_client(store, recognizer) as client:
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            start(socket, session_id)
            socket.send_bytes(FRAME_1)
            assert recognizer.started.wait(timeout=2)
            command(socket, session_id, "capture.stop")
            assert socket.receive_json()["payload"] == {"status": "stopping"}
        assert recognizer.cancelled.is_set()

    assert store.statuses[session_id] is SessionStatus.INTERRUPTED
