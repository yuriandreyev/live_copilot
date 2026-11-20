import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker

from api.application.live_session import LiveSessionGateway
from api.application.use_cases.sessions.create_session import CreateSession
from api.application.use_cases.sessions.get_report import GetReport
from api.application.use_cases.sessions.get_session import GetSession
from api.application.use_cases.sessions.get_transcript import GetTranscript
from api.infrastructure.fake_asr import FakeSpeechRecognizer
from api.infrastructure.storage.database import build_engine
from api.infrastructure.storage.sessions import PostgresSessionRepository
from api.presentation.health import router as health_router
from api.presentation.sessions import register_session_routes
from api.presentation.websocket import websocket_routes
from api.settings import Settings


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
        websocket_routes(LiveSessionGateway(repository, FakeSpeechRecognizer))
    )
    return app
