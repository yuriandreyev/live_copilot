from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from outbox.application.ports.delivery import PendingEvent
from storage.models import OutboxRow


class PostgresOutboxStore:
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def pending(self, limit: int) -> list[PendingEvent]:
        query = (
            select(OutboxRow)
            .where(OutboxRow.published_at.is_(None))
            .order_by(OutboxRow.created_at, OutboxRow.event_id)
            .limit(limit)
        )
        async with self._factory() as db:
            return [
                PendingEvent(row.event_id, row.type, row.payload)
                for row in await db.scalars(query)
            ]

    async def pending_count(self) -> int:
        query = (
            select(func.count())
            .select_from(OutboxRow)
            .where(OutboxRow.published_at.is_(None))
        )
        async with self._factory() as db:
            return await db.scalar(query) or 0

    async def record_attempt(self, event_id: UUID, *, confirmed: bool) -> None:
        query = (
            update(OutboxRow)
            .where(OutboxRow.event_id == event_id, OutboxRow.published_at.is_(None))
            .values(attempts=OutboxRow.attempts + 1)
        )
        if confirmed:
            query = query.values(published_at=func.now())
        async with self._factory.begin() as db:
            await db.execute(query)
