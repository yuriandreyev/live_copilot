from dataclasses import dataclass
from enum import Enum, auto
from typing import Protocol

from agents.public import AgentContext, Recommendation
from session.public import SessionStatus
from transcription.public import TranscriptWindow
from workflows.live_capture.events import RecommendationCreated, TranscriptFinal


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


@dataclass(frozen=True)
class AnalysisUpdate:
    context: AgentContext
    recommendation: Recommendation


type CaptureUpdate = (
    SessionStatus
    | TranscriptWindow
    | CaptureRejected
    | AnalysisUpdate
    | RecommendationCreated
    | TranscriptFinal
)


class CaptureTransport(Protocol):
    async def receive(self, status: SessionStatus) -> CaptureCommand | bytes: ...
    async def publish(self, sequence: int, update: CaptureUpdate) -> None: ...
