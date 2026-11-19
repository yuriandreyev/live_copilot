from enum import StrEnum


class SessionStatus(StrEnum):
    CREATED = "created"
    LIVE = "live"
    STOPPING = "stopping"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"
