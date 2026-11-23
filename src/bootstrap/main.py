import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker

from agents.infrastructure.llama_cpp import LlamaCpp
from agents.public import SupportAnalysis
from bootstrap.health import router as health_router
from bootstrap.settings import Settings
from knowledge.faq import FAQ
from session.application.use_cases.session.create_session import CreateSession
from session.application.use_cases.session.get_report import GetReport
from session.application.use_cases.session.get_session import GetSession
from session.application.use_cases.session.get_transcript import GetTranscript
from session.infrastructure.storage.capture_records import PostgresCaptureRecordStore
from session.infrastructure.storage.database import build_engine
from session.infrastructure.storage.sessions import PostgresSessionRepository
from session.presentation.sessions import register_session_routes
from session.public import SessionLifecycle
from transcription.infrastructure.audio.fake_asr import FakeSpeechRecognizer
from transcription.infrastructure.audio.faster_whisper import FasterWhisper
from transcription.public import SpeechRecognizer
from workflows.live_capture.infrastructure.websocket import websocket_routes
from workflows.live_capture.workflow import LiveCapture


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
                "level": record.levelname,
                "event": record.getMessage(),
                "logger": record.name,
            }
        )


def create_app() -> FastAPI:
    settings = Settings()  # type: ignore[call-arg]  # Loaded from the environment.
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("api")
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(settings.log_level)
    logger.info("api.configured")

    engine = build_engine(settings)
    session_factory = async_sessionmaker(engine)
    repository = PostgresSessionRepository(session_factory)
    capture_records = PostgresCaptureRecordStore(session_factory)
    asr: FasterWhisper | None = None
    llm_client = httpx.AsyncClient(trust_env=False, timeout=12)
    analysis = (
        SupportAnalysis(
            LlamaCpp(llm_client, settings.llm_endpoint, settings.llm_model),
            FAQ().search,
        )
        if settings.llm_enabled
        else None
    )

    def new_recognizer() -> SpeechRecognizer:
        if settings.asr_backend == "fake":
            return FakeSpeechRecognizer()
        if asr is None:
            raise RuntimeError("The ASR model is not loaded.")
        return asr.new_recognizer()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        nonlocal asr
        try:
            if settings.asr_backend == "faster-whisper":
                asr = await asyncio.to_thread(
                    FasterWhisper,
                    settings.asr_model_path,
                    device=settings.asr_device,
                    compute_type=settings.asr_compute_type,
                    language=settings.asr_language,
                )
            yield
        finally:
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
        websocket_routes(
            LiveCapture(
                SessionLifecycle(repository),
                new_recognizer,
                capture_records,
                analysis=analysis,
            )
        )
    )
    web_directory = Path(__file__).with_name("web")
    if not web_directory.is_dir():
        web_directory = Path(__file__).resolve().parents[2] / "web"
    app.mount("/", StaticFiles(directory=web_directory, html=True), name="web")
    return app
