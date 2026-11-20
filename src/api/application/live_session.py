import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from anyio import CancelScope

from api.application.ports import SessionDetails
from api.domain.enums import SessionStatus
from api.domain.session import Session
from copilot_contracts.events import (
    CaptureErrorEvent,
    CaptureErrorPayload,
    CaptureStart,
    CaptureStop,
    ClientCommand,
    EventEnvelope,
    ServerEvent,
    SessionCompleted,
    SessionStatusChanged,
    SessionStatusPayload,
    TranscriptFinal,
    TranscriptInterim,
)
from transcription.application.ports.audio import (
    SAMPLE_BYTES,
    SAMPLE_RATE,
    SpeechRecognizer,
)

MAX_FRAME_BYTES = SAMPLE_RATE * SAMPLE_BYTES // 10

logger = logging.getLogger(__name__)


class LiveSessionStore(Protocol):
    async def get(self, session_id: UUID) -> SessionDetails | None: ...
    async def transition(
        self, session_id: UUID, previous: SessionStatus, target: SessionStatus
    ) -> bool: ...


class ClientDisconnected(Exception):
    pass


class CaptureRejected(Exception):
    def __init__(self, code: str, message: str, close_code: int = 1008) -> None:
        super().__init__(message)
        self.code = code
        self.close_code = close_code


type Receive = Callable[[], Awaitable[ClientCommand | bytes]]
type Send = Callable[[ServerEvent], Awaitable[None]]


class LiveSessionGateway:
    def __init__(
        self,
        store: LiveSessionStore,
        recognizer_factory: Callable[[], SpeechRecognizer],
        *,
        audio_capacity: int = 30,
        flush_timeout: float = 5,
    ) -> None:
        self._store = store
        self._recognizer_factory = recognizer_factory
        self._audio_capacity = audio_capacity
        self._flush_timeout = flush_timeout
        self._admission = asyncio.Lock()

    async def run(self, session_id: UUID, receive: Receive, send: Send) -> int | None:
        session = Session(session_id)
        admitted = False
        try:
            details = await self._store.get(session_id)
            if details is None:
                raise CaptureRejected("unknown_session", "Session does not exist.")
            if details.status is not SessionStatus.CREATED:
                raise CaptureRejected(
                    "session_unavailable", "Session is no longer available."
                )
            try:
                async with asyncio.timeout(10):
                    command = await receive()
            except TimeoutError:
                raise CaptureRejected(
                    "start_timeout", "Timed out waiting for capture.start."
                ) from None
            if isinstance(command, bytes) or command.session_id != session_id:
                raise CaptureRejected(
                    "invalid_command", "Send capture.start for this session first."
                )
            if not isinstance(command, CaptureStart):
                raise CaptureRejected("command_order", "Send capture.start first.")
            if self._admission.locked():
                raise CaptureRejected(
                    "session_busy", "Another capture is active.", 1013
                )

            await self._admission.acquire()
            admitted = True
            recognizer = self._recognizer_factory()
            await self._transition(session, SessionStatus.LIVE)
            await self._capture(session, recognizer, receive, send)
            return 1000
        except (ClientDisconnected, asyncio.CancelledError) as error:
            with CancelScope(shield=True):
                await self._terminate(session, SessionStatus.INTERRUPTED)
            if isinstance(error, asyncio.CancelledError):
                raise
            return None
        except CaptureRejected as error:
            await self._terminate(session, SessionStatus.FAILED)
            return await self._send_error(session, send, error)
        except Exception:
            logger.exception("session.capture_failed session_id=%s", session.id)
            await self._terminate(session, SessionStatus.FAILED)
            failure = CaptureRejected(
                "capture_failed", "Capture could not finish.", 1011
            )
            return await self._send_error(session, send, failure)
        finally:
            if admitted:
                self._admission.release()

    async def _transition(self, session: Session, target: SessionStatus) -> None:
        async def persist() -> None:
            with CancelScope(shield=True):
                if not await self._store.transition(session.id, session.status, target):
                    raise CaptureRejected(
                        "session_unavailable", "Session state changed."
                    )
                session.transition_to(target)

        # Let a state write settle before disconnect cleanup chooses its next transition.
        write = asyncio.create_task(persist())
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await write
            raise

    async def _terminate(self, session: Session, target: SessionStatus) -> None:
        if session.status in (SessionStatus.LIVE, SessionStatus.STOPPING):
            try:
                await self._transition(session, target)
            except Exception:
                logger.exception("session.termination_failed session_id=%s", session.id)

    @staticmethod
    def _envelope(session: Session) -> EventEnvelope:
        return EventEnvelope(
            schema_version=1,
            event_id=uuid4(),
            session_id=session.id,
            correlation_id=session.id,
            sequence=session.next_sequence(),
            occurred_at=datetime.now(UTC),
        )

    async def _send_error(
        self, session: Session, send: Send, error: CaptureRejected
    ) -> int | None:
        try:
            async with asyncio.timeout(2):
                await send(
                    CaptureErrorEvent(
                        **self._envelope(session).model_dump(),
                        event_type="session.overloaded"
                        if error.code == "audio_overload"
                        else "session.error",
                        payload=CaptureErrorPayload(
                            code=error.code, message=str(error)
                        ),
                    )
                )
        except ClientDisconnected:
            return None
        except TimeoutError:
            return 1011
        return error.close_code

    async def _capture(
        self,
        session: Session,
        recognizer: SpeechRecognizer,
        receive: Receive,
        send: Send,
    ) -> None:
        # Reserve one slot for the stop marker so a full audio queue can still be drained.
        audio: asyncio.Queue[bytes | None] = asyncio.Queue(self._audio_capacity + 1)
        outbound: asyncio.Queue[ServerEvent] = asyncio.Queue(8)
        emission = asyncio.Lock()

        async def send_events() -> None:
            while True:
                event = await outbound.get()
                try:
                    async with asyncio.timeout(2):
                        await send(event)
                finally:
                    outbound.task_done()

        async def receive_frames() -> None:
            while True:
                frame = await receive()
                if isinstance(frame, bytes):
                    if (
                        not frame
                        or len(frame) % SAMPLE_BYTES
                        or len(frame) > MAX_FRAME_BYTES
                    ):
                        raise CaptureRejected(
                            "invalid_audio",
                            f"Send 2 to {MAX_FRAME_BYTES} bytes of PCM16 per frame.",
                        )
                    if audio.qsize() >= self._audio_capacity:
                        raise CaptureRejected(
                            "audio_overload",
                            "Audio queue is full. Capture ended.",
                            1013,
                        )
                    audio.put_nowait(frame)
                    continue
                if frame.session_id != session.id:
                    raise CaptureRejected(
                        "invalid_command", "Command session ID must match the socket."
                    )
                if not isinstance(frame, CaptureStop):
                    raise CaptureRejected("command_order", "Capture is already active.")
                break

            try:
                async with asyncio.timeout(self._flush_timeout):
                    await self._transition(session, SessionStatus.STOPPING)
                    async with emission:
                        await outbound.put(
                            SessionStatusChanged(
                                **self._envelope(session).model_dump(),
                                event_type="session.status",
                                payload=SessionStatusPayload(status="stopping"),
                            )
                        )
                    audio.put_nowait(None)
                    await (
                        receive()
                    )  # Keep watching for a disconnect while the processor flushes.
                    raise CaptureRejected("command_order", "Capture is stopping.")
            except TimeoutError:
                raise CaptureRejected(
                    "flush_timeout", "Capture could not flush in time.", 1011
                ) from None

        async def process_frames() -> None:
            while (frame := await audio.get()) is not None:
                result = await recognizer.accept_frame(frame)
                if result is not None:
                    async with emission:
                        await outbound.put(
                            TranscriptInterim(
                                **self._envelope(session).model_dump(),
                                event_type="transcript.interim",
                                payload=result,
                            )
                        )
            result = await recognizer.finish()
            if result is not None:
                await outbound.put(
                    TranscriptFinal(
                        **self._envelope(session).model_dump(),
                        event_type="transcript.final",
                        payload=result,
                    )
                )
            await outbound.join()
            await self._transition(session, SessionStatus.COMPLETED)
            await outbound.put(
                SessionCompleted(
                    **self._envelope(session).model_dump(),
                    event_type="session.completed",
                )
            )
            await outbound.join()

        outbound.put_nowait(
            SessionStatusChanged(
                **self._envelope(session).model_dump(),
                event_type="session.status",
                payload=SessionStatusPayload(status="live"),
            )
        )
        receiver = asyncio.create_task(receive_frames())
        processor = asyncio.create_task(process_frames())
        sender = asyncio.create_task(send_events())
        tasks = (receiver, sender, processor)
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in tasks:
                if task in done:
                    task.result()
        finally:
            for task in tasks:
                task.cancel()
            with CancelScope(shield=True):
                await asyncio.gather(*tasks, return_exceptions=True)
