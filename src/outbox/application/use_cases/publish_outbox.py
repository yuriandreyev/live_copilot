import asyncio
import logging

from outbox.application.ports.delivery import (
    DeliveryUnavailable,
    EventPublisher,
    OutboxStore,
)

logger = logging.getLogger("api.outbox")


class PublishOutbox:
    def __init__(self, store: OutboxStore, publisher: EventPublisher) -> None:
        self._store = store
        self._publisher = publisher

    async def pending_count(self) -> int:
        return await self._store.pending_count()

    async def publish_batch(self) -> int:
        events = await self._store.pending(32)
        for event in events:
            try:
                await self._publisher.publish(event)
            except DeliveryUnavailable:
                await self._store.record_attempt(event.id, confirmed=False)
                raise
            await self._store.record_attempt(event.id, confirmed=True)
        return len(events)

    async def run(self) -> None:
        delay = 0.5
        previous_count = None
        while True:
            try:
                count = await self.pending_count()
                if count != previous_count:
                    logger.info("outbox.pending", extra={"pending_count": count})
                    previous_count = count
                published = await self.publish_batch() if count else 0
            except Exception as error:
                logger.warning(
                    "outbox.poll_failed",
                    extra={
                        "error_category": type(error).__name__,
                        "retry_seconds": delay,
                    },
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5)
            else:
                delay = 0.5
                if published < 32:
                    await asyncio.sleep(delay)
