import asyncio
from uuid import UUID, uuid4

import pytest

from outbox.application.ports.delivery import DeliveryUnavailable, PendingEvent
from outbox.application.use_cases.publish_outbox import PublishOutbox


class Store:
    def __init__(self) -> None:
        self.event = PendingEvent(uuid4(), "session.completed", {})
        self.attempts: list[tuple[UUID, bool]] = []

    async def pending(self, limit: int) -> list[PendingEvent]:
        return [self.event]

    async def pending_count(self) -> int:
        return 1

    async def record_attempt(self, event_id: UUID, *, confirmed: bool) -> None:
        self.attempts.append((event_id, confirmed))


@pytest.mark.parametrize("confirmed", [True, False])
def test_outbox_records_delivery_only_after_confirm(confirmed: bool) -> None:
    store = Store()

    class Publisher:
        async def publish(self, event: PendingEvent) -> None:
            assert store.attempts == []
            assert event == store.event
            if not confirmed:
                raise DeliveryUnavailable

    publisher = PublishOutbox(store, Publisher())
    if confirmed:
        assert asyncio.run(publisher.publish_batch()) == 1
    else:
        with pytest.raises(DeliveryUnavailable):
            asyncio.run(publisher.publish_batch())
    assert store.attempts == [(store.event.id, confirmed)]
