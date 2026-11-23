from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped

from session.application.ports import StoredRecommendation, StoredUtterance
from session.application.ports.capture_records import CaptureWriteError, OutboxEvent
from session.infrastructure.storage.schema import (
    outbox_events,
    recommendations,
    utterances,
)


class _Base(DeclarativeBase):
    pass


class _Utterance(_Base):
    __table__ = utterances

    id: Mapped[UUID]
    session_id: Mapped[UUID]
    sequence: Mapped[int]
    start_ms: Mapped[int]
    end_ms: Mapped[int]
    text: Mapped[str]


class _Recommendation(_Base):
    __table__ = recommendations

    id: Mapped[UUID]
    session_id: Mapped[UUID]
    utterance_id: Mapped[UUID]
    context_version: Mapped[int]
    action: Mapped[str]
    rationale: Mapped[str]
    faq_ids: Mapped[list[str]]
    prompt_version: Mapped[str]


class _OutboxEvent(_Base):
    __table__ = outbox_events


def _enqueue(db: AsyncSession, event: OutboxEvent) -> None:
    db.add(
        _OutboxEvent(
            event_id=event.event_id, type=event.event_type, payload=event.envelope
        )
    )


class PostgresCaptureRecordStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def record_utterance(
        self, session_id: UUID, utterance: StoredUtterance, event: OutboxEvent
    ) -> bool:
        query = (
            insert(_Utterance)
            .values(
                id=utterance.utterance_id,
                session_id=session_id,
                sequence=utterance.sequence,
                start_ms=utterance.start_ms,
                end_ms=utterance.end_ms,
                text=utterance.text,
            )
            .on_conflict_do_nothing(index_elements=[_Utterance.id])
            .returning(_Utterance.id)
        )
        try:
            async with self._factory.begin() as db:
                if await db.scalar(query) is not None:
                    _enqueue(db, event)
                    return True
                existing = await db.get(_Utterance, utterance.utterance_id)
                if existing is None or (
                    existing.session_id,
                    existing.start_ms,
                    existing.end_ms,
                    existing.text,
                ) != (session_id, utterance.start_ms, utterance.end_ms, utterance.text):
                    raise CaptureWriteError("Conflicting finalized utterance.")
                return False
        except SQLAlchemyError as error:
            raise CaptureWriteError("Could not commit finalized utterance.") from error

    async def record_recommendation(
        self,
        session_id: UUID,
        utterance_id: UUID,
        recommendation: StoredRecommendation,
        event: OutboxEvent,
    ) -> bool:
        query = (
            insert(_Recommendation)
            .values(
                id=recommendation.recommendation_id,
                session_id=session_id,
                utterance_id=utterance_id,
                context_version=recommendation.context_version,
                action=recommendation.action,
                rationale=recommendation.rationale,
                faq_ids=list(recommendation.faq_ids),
                prompt_version=recommendation.prompt_version,
            )
            .on_conflict_do_nothing(
                constraint="uq_recommendations_utterance_context_version"
            )
            .returning(_Recommendation.id)
        )
        try:
            async with self._factory.begin() as db:
                if await db.scalar(query) is not None:
                    _enqueue(db, event)
                    return True
                existing = await db.scalar(
                    select(_Recommendation).filter_by(
                        utterance_id=utterance_id,
                        context_version=recommendation.context_version,
                    )
                )
                if existing is None or existing.session_id != session_id:
                    raise CaptureWriteError("Conflicting recommendation.")
                return False
        except SQLAlchemyError as error:
            raise CaptureWriteError("Could not commit recommendation.") from error
