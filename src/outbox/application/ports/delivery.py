from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


class DeliveryUnavailable(Exception):
    """The broker did not confirm delivery."""


@dataclass(frozen=True)
class PendingEvent:
    id: UUID
    type: str
    envelope: dict[str, object]


class OutboxStore(Protocol):
    async def pending(self, limit: int) -> list[PendingEvent]: ...
    async def pending_count(self) -> int: ...
    async def record_attempt(self, event_id: UUID, *, confirmed: bool) -> None: ...


class EventPublisher(Protocol):
    async def publish(self, event: PendingEvent) -> None: ...
