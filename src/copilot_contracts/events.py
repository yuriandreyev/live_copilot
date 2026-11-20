from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter, field_validator

from copilot_contracts.agents import AgentContext, Recommendation
from copilot_contracts.transcription import FinalizedUtterance, TranscriptWindow
from copilot_contracts.types import Contract, NonBlank, PositiveSequence, UtcTimestamp


class Envelope(Contract):
    schema_version: Literal[1]
    session_id: UUID

    @field_validator("schema_version", mode="before")
    @classmethod
    def validate_schema_version_type(cls, version: object) -> object:
        if type(version) is not int:
            raise ValueError("schema_version must be an integer")
        return version


class EmptyPayload(Contract):
    pass


class ClientCommandEnvelope(Envelope):
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


class CaptureStart(ClientCommandEnvelope):
    event_type: Literal["capture.start"]


class CaptureStop(ClientCommandEnvelope):
    event_type: Literal["capture.stop"]


type ClientCommand = Annotated[
    CaptureStart | CaptureStop, Field(discriminator="event_type")
]
client_command_adapter: TypeAdapter[ClientCommand] = TypeAdapter(ClientCommand)


class EventEnvelope(Envelope):
    event_id: UUID
    correlation_id: UUID
    sequence: PositiveSequence
    occurred_at: UtcTimestamp


class TranscriptInterim(EventEnvelope):
    """Transient WebSocket update."""

    event_type: Literal["transcript.interim"]
    payload: TranscriptWindow


class TranscriptFinal(EventEnvelope):
    event_type: Literal["transcript.final"]
    payload: FinalizedUtterance


class AnalysisPayload(Contract):
    utterance_id: UUID
    context_version: PositiveSequence
    context: AgentContext


class AnalysisCompleted(EventEnvelope):
    event_type: Literal["analysis.completed"]
    payload: AnalysisPayload


class RecommendationCreated(EventEnvelope):
    event_type: Literal["recommendation.created"]
    payload: Recommendation


class SessionCompleted(EventEnvelope):
    event_type: Literal["session.completed"]
    payload: EmptyPayload = Field(default_factory=EmptyPayload)


class SessionStatusPayload(Contract):
    status: Literal["live", "stopping"]


class SessionStatusChanged(EventEnvelope):
    event_type: Literal["session.status"]
    payload: SessionStatusPayload


class CaptureErrorPayload(Contract):
    code: NonBlank
    message: NonBlank


class CaptureErrorEvent(EventEnvelope):
    event_type: Literal["session.error", "session.overloaded"]
    payload: CaptureErrorPayload


type DurableEvent = Annotated[
    TranscriptFinal | RecommendationCreated | SessionCompleted,
    Field(discriminator="event_type"),
]
type ServerEvent = Annotated[
    TranscriptInterim
    | TranscriptFinal
    | AnalysisCompleted
    | RecommendationCreated
    | SessionCompleted
    | SessionStatusChanged
    | CaptureErrorEvent,
    Field(discriminator="event_type"),
]
durable_event_adapter: TypeAdapter[DurableEvent] = TypeAdapter(DurableEvent)
server_event_adapter: TypeAdapter[ServerEvent] = TypeAdapter(ServerEvent)
