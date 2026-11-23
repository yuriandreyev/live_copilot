from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from session.application.ports import StoredRecommendation, StoredUtterance


class CaptureWriteError(Exception):
    """A finalized record and its outbox event could not be committed."""


@dataclass(frozen=True)
class OutboxEvent:
    event_id: UUID
    event_type: str
    envelope: dict[str, object]


class CaptureRecordStore(Protocol):
    async def record_utterance(
        self, session_id: UUID, utterance: StoredUtterance, event: OutboxEvent
    ) -> bool: ...

    async def record_recommendation(
        self,
        session_id: UUID,
        utterance_id: UUID,
        recommendation: StoredRecommendation,
        event: OutboxEvent,
    ) -> bool: ...
