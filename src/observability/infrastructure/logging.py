import json
import logging
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "event": record.getMessage(),
            "logger": record.name,
        }
        for field in (
            "session_id",
            "correlation_id",
            "utterance_id",
            "event_id",
            "duration_seconds",
            "error_category",
            "pending_count",
            "retry_seconds",
            "outcome",
        ):
            value = getattr(record, field, None)
            if value is not None:
                entry[field] = value
        return json.dumps(entry, default=str)


def configure_logging(namespace: str, level: str) -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger(namespace)
    logger.handlers[:] = [handler]
    logger.propagate = False
    logger.setLevel(level)
