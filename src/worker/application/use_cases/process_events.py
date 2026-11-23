import asyncio
import logging
from collections.abc import Awaitable, Callable

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
    def __init__(
        self,
        consumer: EventConsumer,
        store: ProcessedEventStore,
        *,
        record_outcome: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._consumer = consumer
        self._store = store
        self._record_outcome = record_outcome

    async def _record(self, outcome: str) -> None:
        if self._record_outcome is not None:
            try:
                await self._record_outcome(outcome)
            except OSError:
                logger.warning(
                    "worker.metrics_write_failed", extra={"error_category": "io"}
                )

    async def process(self, delivery: Delivery) -> None:
        try:
            event = delivery.event()
        except InvalidEvent:
            logger.warning(
                "worker.invalid_event", extra={"error_category": "validation"}
            )
            await self._record("failed")
            await delivery.dead_letter()
            return

        summarize = _summary if event.type == "session.completed" else None
        for delay in (0.25, 0.5, None):
            try:
                async with asyncio.timeout(5):
                    applied = await self._store.apply(event, summarize=summarize)
            except (ProcessingUnavailable, TimeoutError) as error:
                fields = {
                    "event_id": event.id,
                    "session_id": event.session_id,
                    "correlation_id": event.session_id,
                    "error_category": "timeout"
                    if isinstance(error, TimeoutError)
                    else "persistence",
                }
                if delay is None:
                    logger.warning("worker.attempts_exhausted", extra=fields)
                    await self._record("failed")
                    await delivery.dead_letter()
                    return
                await self._record("retried")
                await asyncio.sleep(delay)
            else:
                await delivery.ack()
                outcome = "processed" if applied else "duplicate"
                logger.info(
                    "worker.delivery_acknowledged",
                    extra={
                        "event_id": event.id,
                        "session_id": event.session_id,
                        "correlation_id": event.session_id,
                        "outcome": outcome,
                    },
                )
                await self._record(outcome)
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
                logger.warning(
                    "worker.broker_unavailable",
                    extra={
                        "retry_seconds": delay,
                        "error_category": "broker_unavailable",
                    },
                )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 5)
