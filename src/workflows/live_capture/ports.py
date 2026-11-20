from enum import Enum, auto
from typing import Protocol

from copilot_contracts.transcription import TranscriptWindow
from session.public import SessionStatus


class CaptureDisconnected(Exception):
    pass


class CaptureRejected(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CaptureCommand(Enum):
    START = auto()
    STOP = auto()


class CaptureOutcome(Enum):
    COMPLETED = auto()
    DISCONNECTED = auto()
    DELIVERY_TIMEOUT = auto()


type CaptureUpdate = SessionStatus | TranscriptWindow | CaptureRejected


class CaptureTransport(Protocol):
    async def receive(self, status: SessionStatus) -> CaptureCommand | bytes: ...
    async def publish(self, sequence: int, update: CaptureUpdate) -> None: ...
