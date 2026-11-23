import asyncio
import logging

from worker.application.ports.delivery import (
    ConsumerUnavailable,
    Delivery,
    EventConsumer,
    InvalidEvent,
    ProcessedEventStore,
    ProcessingUnavailable,
)

logger = logging.getLogger(__name__)


def _summary(utterances: int, recommendations: int) -> str:
    return f"Finalized utterances: {utterances}. Recommendations: {recommendations}."


class ProcessEvents:
    def __init__(self, consumer: EventConsumer, store: ProcessedEventStore) -> None:
        self._consumer = consumer
        self._store = store

    async def process(self, delivery: Delivery) -> None:
        try:
            event = delivery.event()
        except InvalidEvent:
            logger.warning("worker.invalid_event")
            await delivery.dead_letter()
            return

        summarize = _summary if event.type == "session.completed" else None
        for delay in (0.25, 0.5, None):
            try:
                async with asyncio.timeout(5):
                    await self._store.apply(event, summarize=summarize)
            except (ProcessingUnavailable, TimeoutError):
                if delay is None:
                    logger.warning("worker.attempts_exhausted event_id=%s", event.id)
                    await delivery.dead_letter()
                    return
                await asyncio.sleep(delay)
            else:
                await delivery.ack()
                return

    async def run(self) -> None:
        delay = 0.5
        while True:
            try:
                async with self._consumer.deliveries() as deliveries:
                    async for delivery in deliveries:
                        await self.process(delivery)
                        delay = 0.5
            except ConsumerUnavailable:
                logger.warning("worker.broker_unavailable retry_seconds=%.1f", delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5)
