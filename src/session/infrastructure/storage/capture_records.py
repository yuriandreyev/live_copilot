from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from session.application.ports import StoredRecommendation, StoredUtterance
from session.application.ports.capture_records import CaptureWriteError, OutboxEvent
from storage.models import OutboxRow, RecommendationRow, UtteranceRow


def _enqueue(db: AsyncSession, event: OutboxEvent) -> None:
    db.add(
        OutboxRow(
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
            insert(UtteranceRow)
            .values(
                id=utterance.utterance_id,
                session_id=session_id,
                sequence=utterance.sequence,
                start_ms=utterance.start_ms,
                end_ms=utterance.end_ms,
                text=utterance.text,
            )
            .on_conflict_do_nothing(index_elements=[UtteranceRow.id])
            .returning(UtteranceRow.id)
        )
        try:
            async with self._factory.begin() as db:
                if await db.scalar(query) is not None:
                    _enqueue(db, event)
                    return True
                existing = await db.get(UtteranceRow, utterance.utterance_id)
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
            insert(RecommendationRow)
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
            .returning(RecommendationRow.id)
        )
        try:
            async with self._factory.begin() as db:
                if await db.scalar(query) is not None:
                    _enqueue(db, event)
                    return True
                existing = await db.scalar(
                    select(RecommendationRow).filter_by(
                        utterance_id=utterance_id,
                        context_version=recommendation.context_version,
                    )
                )
                if existing is None or existing.session_id != session_id:
                    raise CaptureWriteError("Conflicting recommendation.")
                return False
        except SQLAlchemyError as error:
            raise CaptureWriteError("Could not commit recommendation.") from error
