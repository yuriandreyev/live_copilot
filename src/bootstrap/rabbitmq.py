from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import aio_pika
from aio_pika.abc import AbstractConnection, AbstractExchange, AbstractQueue

from bootstrap.settings import Settings


@asynccontextmanager
async def open_connection(settings: Settings) -> AsyncIterator[AbstractConnection]:
    async with await aio_pika.connect(
        host=settings.rabbitmq_host,
        port=settings.rabbitmq_port,
        login=settings.rabbitmq_default_user,
        password=settings.rabbitmq_default_pass.get_secret_value(),
        timeout=3,
    ) as connection:
        yield connection


async def broker_ready(settings: Settings) -> bool:
    async with open_connection(settings) as connection:
        return not connection.is_closed


@asynccontextmanager
async def open_topology(
    settings: Settings,
) -> AsyncIterator[tuple[AbstractExchange, AbstractQueue]]:
    async with open_connection(settings) as connection:
        async with connection.channel(
            publisher_confirms=True, on_return_raises=True
        ) as channel:
            await channel.set_qos(prefetch_count=8, timeout=3)
            name = settings.rabbitmq_queue
            dead = await channel.declare_exchange(
                f"{name}.dead", "fanout", durable=True, timeout=3
            )
            dead_queue = await channel.declare_queue(
                f"{name}.dead", durable=True, timeout=3
            )
            await dead_queue.bind(dead, timeout=3)
            exchange = await channel.declare_exchange(
                f"{name}.events", "fanout", durable=True, timeout=3
            )
            queue = await channel.declare_queue(
                name,
                durable=True,
                arguments={
                    "x-queue-type": "quorum",
                    "x-delivery-limit": 5,
                    "x-dead-letter-exchange": dead.name,
                },
                timeout=3,
            )
            await queue.bind(exchange, timeout=3)
            yield exchange, queue


@asynccontextmanager
async def open_exchange(settings: Settings) -> AsyncIterator[AbstractExchange]:
    async with open_topology(settings) as (exchange, _):
        yield exchange


@asynccontextmanager
async def open_queue(settings: Settings) -> AsyncIterator[AbstractQueue]:
    async with open_topology(settings) as (_, queue):
        yield queue
