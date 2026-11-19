import json
import logging
from datetime import UTC, datetime

from fastapi import FastAPI

from api.presentation.health import router as health_router
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

    app = FastAPI(title="Live AI Copilot")
    app.include_router(health_router)
    return app
