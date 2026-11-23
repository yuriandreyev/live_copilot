import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.infrastructure.llama_cpp import LlamaCpp
from agents.public import SupportAnalysis
from bootstrap.health import router as health_router
from bootstrap.rabbitmq import broker_ready, open_exchange
from bootstrap.settings import Settings
from knowledge.faq import FAQ
from observability.application.use_cases.check_readiness import CheckReadiness
from observability.infrastructure.logging import configure_logging
from observability.infrastructure.metrics import Metrics
from observability.infrastructure.worker_metrics import WorkerMetrics
from observability.presentation.http import routes as observability_routes
from outbox.application.use_cases.publish_outbox import PublishOutbox
from outbox.infrastructure.postgres import PostgresOutboxStore
from outbox.infrastructure.rabbitmq import RabbitMQPublisher
from session.application.use_cases.session.create_session import CreateSession
from session.application.use_cases.session.get_report import GetReport
from session.application.use_cases.session.get_session import GetSession
from session.application.use_cases.session.get_transcript import GetTranscript
from session.infrastructure.storage.capture_records import PostgresCaptureRecordStore
from session.infrastructure.storage.database import build_engine
from session.infrastructure.storage.sessions import PostgresSessionRepository
from session.presentation.sessions import register_session_routes
from session.public import SessionLifecycle
from storage.models import OutboxRow
from transcription.infrastructure.audio.fake_asr import FakeSpeechRecognizer
from transcription.infrastructure.audio.faster_whisper import FasterWhisper
from transcription.public import SpeechRecognizer
from workflows.live_capture.infrastructure.websocket import websocket_routes
from workflows.live_capture.ports import CaptureRejected
from workflows.live_capture.workflow import LiveCapture


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]  # Loaded from the environment.
    configure_logging("api", settings.log_level)
    logger = logging.getLogger("api")
    logger.info("api.configured")

    engine = build_engine(settings)
    session_factory = async_sessionmaker(engine)
    repository = PostgresSessionRepository(session_factory)
    capture_records = PostgresCaptureRecordStore(session_factory)
    asr: FasterWhisper | None = None
    llm_client = httpx.AsyncClient(trust_env=False, timeout=12)
    llm = (
        LlamaCpp(llm_client, settings.llm_endpoint, settings.llm_model)
        if settings.llm_enabled
        else None
    )
    analysis = SupportAnalysis(llm, FAQ().search) if llm is not None else None
    metrics = Metrics()
    worker_metrics = WorkerMetrics(settings.worker_metrics_path)
    outbox_store = PostgresOutboxStore(session_factory)

    async def postgres_ready() -> bool:
        async with session_factory() as db:
            await db.scalar(select(OutboxRow.event_id).limit(1))
            return True

    async def asr_ready() -> bool:
        return settings.asr_backend == "fake" or asr is not None

    readiness = CheckReadiness(
        {
            "postgres": postgres_ready,
            "rabbitmq": lambda: broker_ready(settings),
            "asr": asr_ready,
            "llm": llm.ready if llm is not None else None,
        }
    )

    def new_recognizer() -> SpeechRecognizer:
        if settings.asr_backend == "fake":
            return FakeSpeechRecognizer()
        if asr is None:
            raise CaptureRejected(
                "asr_unavailable", "The speech recognition model is unavailable."
            )
        return asr.new_recognizer()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal asr
        publisher = RabbitMQPublisher(lambda: open_exchange(settings))
        publisher_task = None
        try:
            if settings.asr_backend == "faster-whisper":
                try:
                    asr = await asyncio.to_thread(
                        FasterWhisper,
                        settings.asr_model_path,
                        device=settings.asr_device,
                        compute_type=settings.asr_compute_type,
                        language=settings.asr_language,
                    )
                except Exception:
                    logger.error(
                        "asr.load_failed", extra={"error_category": "model_unavailable"}
                    )
            if settings.outbox_enabled:
                outbox = PublishOutbox(outbox_store, publisher)
                publisher_task = asyncio.create_task(outbox.run())
            yield
        finally:
            if publisher_task is not None:
                publisher_task.cancel()
                await asyncio.gather(publisher_task, return_exceptions=True)
            await publisher.close()
            if asr is not None:
                asr.close()
                asr = None
            await llm_client.aclose()
            await engine.dispose()

    app = FastAPI(title="Live AI Copilot", lifespan=lifespan)
    register_session_routes(
        app,
        create_session_use_case=CreateSession(repository),
        get_session_use_case=GetSession(repository),
        get_transcript_use_case=GetTranscript(repository),
        get_report_use_case=GetReport(repository),
    )
    app.include_router(health_router)
    app.include_router(
        observability_routes(
            readiness, metrics, outbox_store.pending_count, worker_metrics.read
        )
    )
    app.include_router(
        websocket_routes(
            LiveCapture(
                SessionLifecycle(repository),
                new_recognizer,
                capture_records,
                analysis=analysis,
                metrics=metrics,
            )
        )
    )
    web_directory = Path(__file__).with_name("web")
    if not web_directory.is_dir():
        web_directory = Path(__file__).resolve().parents[2] / "web"
    app.mount("/", StaticFiles(directory=web_directory, html=True), name="web")
    return app
