import asyncio
import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from itertools import count
from uuid import UUID

from anyio import CancelScope

from session.public import SessionLifecycle, SessionStatus
from transcription.public import SpeechRecognizer
from workflows.live_capture.ports import (
    CaptureCommand,
    CaptureDisconnected,
    CaptureOutcome,
    CaptureRejected,
    CaptureTransport,
    CaptureUpdate,
)

logger = logging.getLogger(__name__)


@dataclass
class _CaptureState:
    id: UUID
    status: SessionStatus = SessionStatus.CREATED
    sequence: Iterator[int] = field(default_factory=lambda: count(1))


class LiveCapture:
    def __init__(
        self,
        lifecycle: SessionLifecycle,
        recognizer_factory: Callable[[], SpeechRecognizer],
        *,
        audio_capacity: int = 30,
        flush_timeout: float = 5,
    ) -> None:
        self._lifecycle = lifecycle
        self._recognizer_factory = recognizer_factory
        self._audio_capacity = audio_capacity
        self._flush_timeout = flush_timeout
        self._admission = asyncio.Lock()

    async def run(
        self, session_id: UUID, transport: CaptureTransport
    ) -> CaptureOutcome | CaptureRejected:
        session = _CaptureState(session_id)
        admitted = False
        try:
            status = await self._lifecycle.get_status(session_id)
            if status is None:
                raise CaptureRejected("unknown_session", "Session does not exist.")
            if status is not SessionStatus.CREATED:
                raise CaptureRejected(
                    "session_unavailable", "Session is no longer available."
                )
            try:
                async with asyncio.timeout(10):
                    command = await transport.receive(session.status)
            except TimeoutError:
                raise CaptureRejected(
                    "start_timeout", "Timed out waiting for capture.start."
                ) from None
            if isinstance(command, bytes):
                raise CaptureRejected(
                    "invalid_command", "Start capture before sending audio."
                )
            if command is not CaptureCommand.START:
                raise CaptureRejected("command_order", "Send capture.start first.")
            if self._admission.locked():
                raise CaptureRejected("session_busy", "Another capture is active.")

            await self._admission.acquire()
            admitted = True
            recognizer = self._recognizer_factory()
            await self._transition(session, SessionStatus.LIVE)
            await self._capture(session, recognizer, transport)
            return CaptureOutcome.COMPLETED
        except (CaptureDisconnected, asyncio.CancelledError) as error:
            with CancelScope(shield=True):
                await self._terminate(session, SessionStatus.INTERRUPTED)
            if isinstance(error, asyncio.CancelledError):
                raise
            return CaptureOutcome.DISCONNECTED
        except CaptureRejected as error:
            await self._terminate(session, SessionStatus.FAILED)
            return await self._send_error(session, transport, error)
        except Exception:
            logger.exception("session.capture_failed session_id=%s", session.id)
            await self._terminate(session, SessionStatus.FAILED)
            failure = CaptureRejected("capture_failed", "Capture could not finish.")
            return await self._send_error(session, transport, failure)
        finally:
            if admitted:
                self._admission.release()

    async def _transition(self, session: _CaptureState, target: SessionStatus) -> None:
        async def persist() -> None:
            with CancelScope(shield=True):
                if not await self._lifecycle.transition(
                    session.id, session.status, target
                ):
                    raise CaptureRejected(
                        "session_unavailable", "Session state changed."
                    )
                session.status = target

        # Let a state write settle before disconnect cleanup chooses its next transition.
        write = asyncio.create_task(persist())
        try:
            await asyncio.shield(write)
        except asyncio.CancelledError:
            with CancelScope(shield=True):
                await write
            raise

    async def _terminate(self, session: _CaptureState, target: SessionStatus) -> None:
        if session.status in (SessionStatus.LIVE, SessionStatus.STOPPING):
            try:
                await self._transition(session, target)
            except Exception:
                logger.exception("session.termination_failed session_id=%s", session.id)

    async def _send_error(
        self,
        session: _CaptureState,
        transport: CaptureTransport,
        error: CaptureRejected,
    ) -> CaptureOutcome | CaptureRejected:
        try:
            async with asyncio.timeout(2):
                await transport.publish(next(session.sequence), error)
        except CaptureDisconnected:
            return CaptureOutcome.DISCONNECTED
        except TimeoutError:
            return CaptureOutcome.DELIVERY_TIMEOUT
        return error

    async def _capture(
        self,
        session: _CaptureState,
        recognizer: SpeechRecognizer,
        transport: CaptureTransport,
    ) -> None:
        # Reserve one slot for the stop marker so a full audio queue can still be drained.
        audio: asyncio.Queue[bytes | None] = asyncio.Queue(self._audio_capacity + 1)
        outbound: asyncio.Queue[tuple[int, CaptureUpdate]] = asyncio.Queue(8)
        emission = asyncio.Lock()

        async def send_events() -> None:
            while True:
                event = await outbound.get()
                try:
                    async with asyncio.timeout(2):
                        await transport.publish(*event)
                finally:
                    outbound.task_done()

        async def receive_frames() -> None:
            while True:
                frame = await transport.receive(session.status)
                if isinstance(frame, bytes):
                    if audio.qsize() >= self._audio_capacity:
                        raise CaptureRejected(
                            "audio_overload",
                            "Audio queue is full. Capture ended.",
                        )
                    audio.put_nowait(frame)
                    continue
                if frame is not CaptureCommand.STOP:
                    raise CaptureRejected("command_order", "Capture is already active.")
                break

            try:
                async with asyncio.timeout(self._flush_timeout):
                    await self._transition(session, SessionStatus.STOPPING)
                    async with emission:
                        await outbound.put((next(session.sequence), session.status))
                    audio.put_nowait(None)
                    await transport.receive(
                        session.status
                    )  # Keep watching for a disconnect while the processor flushes.
                    raise CaptureRejected("command_order", "Capture is stopping.")
            except TimeoutError:
                raise CaptureRejected(
                    "flush_timeout", "Capture could not flush in time."
                ) from None

        async def process_frames() -> None:
            while (frame := await audio.get()) is not None:
                result = await recognizer.accept_frame(frame)
                if result is not None:
                    async with emission:
                        await outbound.put((next(session.sequence), result))
            result = await recognizer.finish()
            if result is not None:
                await outbound.put((next(session.sequence), result))
            await outbound.join()
            await self._transition(session, SessionStatus.COMPLETED)
            await outbound.put((next(session.sequence), session.status))
            await outbound.join()

        outbound.put_nowait((next(session.sequence), session.status))
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
