import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.ext.asyncio import async_sessionmaker

from bootstrap.health import router as health_router
from bootstrap.settings import Settings
from session.application.use_cases.session.create_session import CreateSession
from session.application.use_cases.session.get_report import GetReport
from session.application.use_cases.session.get_session import GetSession
from session.application.use_cases.session.get_transcript import GetTranscript
from session.infrastructure.storage.database import build_engine
from session.infrastructure.storage.sessions import PostgresSessionRepository
from session.presentation.sessions import register_session_routes
from session.public import SessionLifecycle
from transcription.infrastructure.audio.fake_asr import FakeSpeechRecognizer
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
    repository = PostgresSessionRepository(async_sessionmaker(engine))

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
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
            LiveCapture(SessionLifecycle(repository), FakeSpeechRecognizer)
        )
    )
    web_directory = Path(__file__).with_name("web")
    if not web_directory.is_dir():
        web_directory = Path(__file__).resolve().parents[2] / "web"
    app.mount("/", StaticFiles(directory=web_directory, html=True), name="web")
    return app
