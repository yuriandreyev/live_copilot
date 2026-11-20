from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from api.domain.enums import SessionStatus
from api.domain.session import Session


@dataclass(frozen=True)
class SessionDetails:
    session_id: UUID
    status: SessionStatus
    created_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    summary_available: bool


@dataclass(frozen=True)
class StoredRecommendation:
    recommendation_id: UUID
    context_version: int
    action: str
    rationale: str
    faq_ids: tuple[str, ...]
    prompt_version: str


@dataclass(frozen=True)
class StoredUtterance:
    utterance_id: UUID
    sequence: int
    start_ms: int
    end_ms: int
    text: str
    recommendations: tuple[StoredRecommendation, ...]


@dataclass(frozen=True)
class SessionTranscript:
    session_id: UUID
    utterances: tuple[StoredUtterance, ...]


@dataclass(frozen=True)
class SessionReport:
    session_id: UUID
    summary: str | None
    summary_created_at: datetime | None


class SessionRepository(Protocol):
    async def create(self, session: Session) -> None: ...
    async def get(self, session_id: UUID) -> SessionDetails | None: ...
    async def get_transcript(self, session_id: UUID) -> SessionTranscript | None: ...
    async def get_report(self, session_id: UUID) -> SessionReport | None: ...
