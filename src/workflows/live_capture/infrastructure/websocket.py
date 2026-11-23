from uuid import UUID

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from session.public import SessionStatus
from transcription.public import (
    SAMPLE_BYTES,
    SAMPLE_RATE,
    TranscriptWindow,
)
from workflows.live_capture.events import (
    AnalysisCompleted,
    AnalysisPayload,
    CaptureErrorEvent,
    CaptureErrorPayload,
    CaptureStart,
    RecommendationCreated,
    ServerEvent,
    SessionCompleted,
    SessionStatusChanged,
    SessionStatusPayload,
    TranscriptFinal,
    TranscriptInterim,
    TranscriptInterimPayload,
    client_command_adapter,
    new_envelope,
)
from workflows.live_capture.ports import (
    AnalysisUpdate,
    CaptureCommand,
    CaptureDisconnected,
    CaptureOutcome,
    CaptureRejected,
    CaptureUpdate,
)
from workflows.live_capture.workflow import LiveCapture

MAX_FRAME_BYTES = SAMPLE_RATE * SAMPLE_BYTES // 10

_ERROR_CLOSE_CODES = {
    "session_busy": 1013,
    "audio_overload": 1013,
    "capture_failed": 1011,
    "flush_timeout": 1011,
    "persistence_failed": 1011,
}


def _server_event(
    session_id: UUID, sequence: int, update: CaptureUpdate
) -> ServerEvent:
    if isinstance(update, (TranscriptFinal, RecommendationCreated)):
        return update
    envelope = new_envelope(session_id, sequence).model_dump()

    if isinstance(update, CaptureRejected):
        return CaptureErrorEvent(
            **envelope,
            event_type="session.overloaded"
            if update.code == "audio_overload"
            else "session.error",
            payload=CaptureErrorPayload(code=update.code, message=str(update)),
        )
    if isinstance(update, AnalysisUpdate):
        return AnalysisCompleted(
            **envelope,
            event_type="analysis.completed",
            payload=AnalysisPayload(
                utterance_id=update.recommendation.utterance_id,
                context_version=update.recommendation.context_version,
                context=update.context,
            ),
        )
    if isinstance(update, TranscriptWindow):
        return TranscriptInterim(
            **envelope,
            event_type="transcript.interim",
            payload=TranscriptInterimPayload(
                start_ms=update.start_ms, end_ms=update.end_ms, text=update.text
            ),
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


class WebSocketCaptureTransport:
    def __init__(self, socket: WebSocket, session_id: UUID) -> None:
        self._socket = socket
        self._session_id = session_id

    async def receive(self, status: SessionStatus) -> CaptureCommand | bytes:
        message = await self._socket.receive()
        if message["type"] == "websocket.disconnect":
            raise CaptureDisconnected
        frame = message.get("bytes")
        if frame is not None:
            if status is SessionStatus.CREATED:
                raise CaptureRejected(
                    "invalid_command", "Send capture.start for this session first."
                )
            if status is SessionStatus.LIVE and (
                not frame or len(frame) % SAMPLE_BYTES or len(frame) > MAX_FRAME_BYTES
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
        if command.session_id != self._session_id:
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

    async def publish(self, sequence: int, update: CaptureUpdate) -> None:
        event = _server_event(self._session_id, sequence, update)
        try:
            await self._socket.send_text(event.model_dump_json())
        except (WebSocketDisconnect, OSError):
            raise CaptureDisconnected from None

    async def close(self, outcome: CaptureOutcome | CaptureRejected) -> None:
        if outcome is CaptureOutcome.DISCONNECTED:
            return
        if isinstance(outcome, CaptureRejected):
            close_code = _ERROR_CLOSE_CODES.get(outcome.code, 1008)
        else:
            close_code = 1000 if outcome is CaptureOutcome.COMPLETED else 1011
        try:
            await self._socket.close(code=close_code)
        except (WebSocketDisconnect, OSError):
            pass


def websocket_routes(live_capture: LiveCapture) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/sessions/{session_id}")
    async def capture(socket: WebSocket, session_id: UUID) -> None:
        await socket.accept()
        transport = WebSocketCaptureTransport(socket, session_id)
        outcome = await live_capture.run(session_id, transport)
        await transport.close(outcome)

    return router
