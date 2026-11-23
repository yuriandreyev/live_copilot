import json
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, AsyncExitStack

from aio_pika import DeliveryMode, Message
from aio_pika.abc import AbstractExchange
from aio_pika.exceptions import AMQPError
from pamqp.commands import Basic

from outbox.application.ports.delivery import DeliveryUnavailable, PendingEvent


class RabbitMQPublisher:
    def __init__(
        self, open_exchange: Callable[[], AbstractAsyncContextManager[AbstractExchange]]
    ) -> None:
        self._open_exchange = open_exchange
        self._stack = AsyncExitStack()
        self._exchange: AbstractExchange | None = None

    async def close(self) -> None:
        self._exchange = None
        await self._stack.aclose()

    async def publish(self, event: PendingEvent) -> None:
        try:
            if self._exchange is None:
                self._exchange = await self._stack.enter_async_context(
                    self._open_exchange()
                )
            confirm = await self._exchange.publish(
                Message(
                    json.dumps(event.envelope).encode(),
                    content_type="application/json",
                    delivery_mode=DeliveryMode.PERSISTENT,
                    message_id=str(event.id),
                    type=event.type,
                ),
                routing_key=event.type,
                mandatory=True,
                timeout=3,
            )
            if isinstance(confirm, Basic.Ack):
                return
        except (AMQPError, OSError, RuntimeError) as error:
            await self.close()
            raise DeliveryUnavailable from error
        await self.close()
        raise DeliveryUnavailable("RabbitMQ did not acknowledge delivery.")
