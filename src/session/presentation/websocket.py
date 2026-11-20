from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from copilot_contracts.events import (
    CaptureErrorEvent,
    CaptureErrorPayload,
    CaptureStart,
    EventEnvelope,
    ServerEvent,
    SessionCompleted,
    SessionStatusChanged,
    SessionStatusPayload,
    TranscriptFinal,
    TranscriptInterim,
    client_command_adapter,
)
from copilot_contracts.transcription import FinalizedUtterance, TranscriptWindow
from session.application.use_cases.session.live_capture import (
    CaptureCommand,
    CaptureDisconnected,
    CaptureOutcome,
    CaptureRejected,
    CaptureUpdate,
    LiveCapture,
)
from session.domain.enums import SessionStatus
from transcription.application.ports.audio import SAMPLE_BYTES, SAMPLE_RATE

MAX_FRAME_BYTES = SAMPLE_RATE * SAMPLE_BYTES // 10

_ERROR_CLOSE_CODES = {
    "session_busy": 1013,
    "audio_overload": 1013,
    "capture_failed": 1011,
    "flush_timeout": 1011,
}


def _server_event(
    session_id: UUID, sequence: int, update: CaptureUpdate
) -> ServerEvent:
    envelope = EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        session_id=session_id,
        correlation_id=session_id,
        sequence=sequence,
        occurred_at=datetime.now(UTC),
    ).model_dump()

    if isinstance(update, CaptureRejected):
        return CaptureErrorEvent(
            **envelope,
            event_type="session.overloaded"
            if update.code == "audio_overload"
            else "session.error",
            payload=CaptureErrorPayload(code=update.code, message=str(update)),
        )
    if isinstance(update, FinalizedUtterance):
        return TranscriptFinal(
            **envelope, event_type="transcript.final", payload=update
        )
    if isinstance(update, TranscriptWindow):
        return TranscriptInterim(
            **envelope, event_type="transcript.interim", payload=update
        )
    if update is SessionStatus.COMPLETED:
        return SessionCompleted(**envelope, event_type="session.completed")
    assert update in (SessionStatus.LIVE, SessionStatus.STOPPING)
    return SessionStatusChanged(
        **envelope,
        event_type="session.status",
        payload=SessionStatusPayload(
            status="live" if update is SessionStatus.LIVE else "stopping"
        ),
    )


def websocket_routes(live_capture: LiveCapture) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/sessions/{session_id}")
    async def capture(socket: WebSocket, session_id: UUID) -> None:
        await socket.accept()

        async def receive(status: SessionStatus) -> CaptureCommand | bytes:
            message = await socket.receive()
            if message["type"] == "websocket.disconnect":
                raise CaptureDisconnected
            frame = message.get("bytes")
            if frame is not None:
                if status is SessionStatus.CREATED:
                    raise CaptureRejected(
                        "invalid_command", "Send capture.start for this session first."
                    )
                if status is SessionStatus.LIVE and (
                    not frame
                    or len(frame) % SAMPLE_BYTES
                    or len(frame) > MAX_FRAME_BYTES
                ):
                    raise CaptureRejected(
                        "invalid_audio",
                        f"Send 2 to {MAX_FRAME_BYTES} bytes of PCM16 per frame.",
                    )
                return frame
            try:
                command = client_command_adapter.validate_json(message["text"])
            except ValidationError:
                raise CaptureRejected(
                    "invalid_command", "Send a valid versioned capture command."
                ) from None
            if command.session_id != session_id:
                if status is SessionStatus.CREATED:
                    raise CaptureRejected(
                        "invalid_command", "Send capture.start for this session first."
                    )
                if status is SessionStatus.LIVE:
                    raise CaptureRejected(
                        "invalid_command", "Command session ID must match the socket."
                    )
            return (
                CaptureCommand.START
                if isinstance(command, CaptureStart)
                else CaptureCommand.STOP
            )

        async def send(sequence: int, update: CaptureUpdate) -> None:
            event = _server_event(session_id, sequence, update)
            try:
                await socket.send_text(event.model_dump_json())
            except (WebSocketDisconnect, OSError):
                raise CaptureDisconnected from None

        outcome = await live_capture.run(session_id, receive, send)
        if outcome is CaptureOutcome.DISCONNECTED:
            return
        if isinstance(outcome, CaptureRejected):
            close_code = _ERROR_CLOSE_CODES.get(outcome.code, 1008)
        else:
            close_code = 1000 if outcome is CaptureOutcome.COMPLETED else 1011
        try:
            await socket.close(code=close_code)
        except (WebSocketDisconnect, OSError):
            pass

    return router
