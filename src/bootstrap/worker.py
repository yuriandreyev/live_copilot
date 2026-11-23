import asyncio
import signal

from sqlalchemy.ext.asyncio import async_sessionmaker

from bootstrap.rabbitmq import open_queue
from bootstrap.settings import Settings
from observability.infrastructure.logging import configure_logging
from observability.infrastructure.worker_metrics import WorkerMetrics
from session.infrastructure.storage.database import build_engine
from worker.application.use_cases.process_events import ProcessEvents
from worker.infrastructure.postgres import PostgresProcessedEventStore
from worker.infrastructure.rabbitmq import RabbitMQConsumer


async def run_worker() -> None:
    settings = Settings()  # type: ignore[call-arg]
    configure_logging("worker", settings.log_level)
    engine = build_engine(settings)
    worker = ProcessEvents(
        RabbitMQConsumer(lambda: open_queue(settings)),
        PostgresProcessedEventStore(async_sessionmaker(engine)),
        record_outcome=WorkerMetrics(settings.worker_metrics_path).record,
    )
    task = asyncio.create_task(worker.run())
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGTERM, task.cancel)
    try:
        await task
    except asyncio.CancelledError:
        pass
    finally:
        loop.remove_signal_handler(signal.SIGTERM)
        await engine.dispose()
