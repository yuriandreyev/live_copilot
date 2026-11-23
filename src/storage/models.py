from datetime import datetime
from uuid import UUID

from sqlalchemy.orm import DeclarativeBase, Mapped

from storage.schema import (
    outbox_events,
    processed_events,
    recommendations,
    session_summaries,
    utterances,
)


class Base(DeclarativeBase):
    pass


class UtteranceRow(Base):
    __table__ = utterances

    id: Mapped[UUID]
    session_id: Mapped[UUID]
    sequence: Mapped[int]
    start_ms: Mapped[int]
    end_ms: Mapped[int]
    text: Mapped[str]


class RecommendationRow(Base):
    __table__ = recommendations

    id: Mapped[UUID]
    session_id: Mapped[UUID]
    utterance_id: Mapped[UUID]
    context_version: Mapped[int]
    action: Mapped[str]
    rationale: Mapped[str]
    faq_ids: Mapped[list[str]]
    prompt_version: Mapped[str]


class OutboxRow(Base):
    __table__ = outbox_events

    event_id: Mapped[UUID]
    type: Mapped[str]
    payload: Mapped[dict[str, object]]
    created_at: Mapped[datetime]
    published_at: Mapped[datetime | None]
    attempts: Mapped[int]


class ProcessedEventRow(Base):
    __table__ = processed_events

    event_id: Mapped[UUID]


class SummaryRow(Base):
    __table__ = session_summaries
