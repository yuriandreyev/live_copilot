from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from storage.models import (
    ProcessedEventRow,
    RecommendationRow,
    SummaryRow,
    UtteranceRow,
)
from worker.application.ports.delivery import ProcessingUnavailable, SessionEvent

_CONSUMER_NAME = "session-worker-v1"


class PostgresProcessedEventStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def apply(
        self, event: SessionEvent, *, summarize: Callable[[int, int], str] | None
    ) -> None:
        claim = (
            insert(ProcessedEventRow)
            .values(consumer_name=_CONSUMER_NAME, event_id=event.id)
            .on_conflict_do_nothing()
            .returning(ProcessedEventRow.event_id)
        )
        try:
            async with self._factory.begin() as db:
                if await db.scalar(claim) is None or summarize is None:
                    return
                utterances = await db.scalar(
                    select(func.count())
                    .select_from(UtteranceRow)
                    .where(UtteranceRow.session_id == event.session_id)
                )
                recommendations = await db.scalar(
                    select(func.count())
                    .select_from(RecommendationRow)
                    .where(RecommendationRow.session_id == event.session_id)
                )
                await db.execute(
                    insert(SummaryRow)
                    .values(
                        session_id=event.session_id,
                        summary=summarize(utterances or 0, recommendations or 0),
                    )
                    .on_conflict_do_nothing()
                )
        except (SQLAlchemyError, OSError) as error:
            raise ProcessingUnavailable from error
