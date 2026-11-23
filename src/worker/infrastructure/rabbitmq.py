from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated
from uuid import UUID

from aio_pika.abc import AbstractIncomingMessage, AbstractQueue
from aio_pika.exceptions import AMQPError
from pydantic import BaseModel, Field, ValidationError

from worker.application.ports.delivery import (
    ConsumerUnavailable,
    Delivery,
    EventType,
    InvalidEvent,
    SessionEvent,
)


class _EventEnvelope(BaseModel):
    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    event_id: UUID
    session_id: UUID
    event_type: EventType


class _RabbitDelivery:
    def __init__(self, message: AbstractIncomingMessage) -> None:
        self._message = message

    def event(self) -> SessionEvent:
        try:
            envelope = _EventEnvelope.model_validate_json(self._message.body)
        except ValidationError as error:
            raise InvalidEvent from error
        if self._message.message_id != str(envelope.event_id):
            raise InvalidEvent
        return SessionEvent(envelope.event_id, envelope.session_id, envelope.event_type)

    async def ack(self) -> None:
        await self._message.ack()

    async def dead_letter(self) -> None:
        await self._message.reject(requeue=False)


class RabbitMQConsumer:
    def __init__(
        self, open_queue: Callable[[], AbstractAsyncContextManager[AbstractQueue]]
    ) -> None:
        self._open_queue = open_queue

    @asynccontextmanager
    async def deliveries(self) -> AsyncIterator[AsyncIterator[Delivery]]:
        try:
            async with self._open_queue() as queue, queue.iterator() as messages:
                yield (_RabbitDelivery(message) async for message in messages)
        except (AMQPError, OSError, RuntimeError) as error:
            raise ConsumerUnavailable from error
