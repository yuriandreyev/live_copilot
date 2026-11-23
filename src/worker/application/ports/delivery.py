from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

type EventType = Literal[
    "transcript.final", "recommendation.created", "session.completed"
]


class InvalidEvent(Exception):
    pass


class ConsumerUnavailable(Exception):
    pass


class ProcessingUnavailable(Exception):
    pass


@dataclass(frozen=True)
class SessionEvent:
    id: UUID
    session_id: UUID
    type: EventType


class Delivery(Protocol):
    def event(self) -> SessionEvent: ...
    async def ack(self) -> None: ...
    async def dead_letter(self) -> None: ...


class EventConsumer(Protocol):
    def deliveries(self) -> AbstractAsyncContextManager[AsyncIterator[Delivery]]: ...


class ProcessedEventStore(Protocol):
    async def apply(
        self, event: SessionEvent, *, summarize: Callable[[int, int], str] | None
    ) -> None: ...
