from datetime import UTC, datetime
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import Field, TypeAdapter, field_validator, model_validator

from agents.public import AgentContext, Recommendation
from workflows.live_capture.event_types import (
    Contract,
    NonBlank,
    PositiveSequence,
    UtcTimestamp,
)


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


def new_envelope(session_id: UUID, sequence: int) -> EventEnvelope:
    return EventEnvelope(
        schema_version=1,
        event_id=uuid4(),
        session_id=session_id,
        correlation_id=session_id,
        sequence=sequence,
        occurred_at=datetime.now(UTC),
    )


Milliseconds = Annotated[int, Field(strict=True, ge=0)]


class TranscriptInterimPayload(Contract):
    start_ms: Milliseconds
    end_ms: Milliseconds
    text: NonBlank

    @model_validator(mode="after")
    def validate_audio_window(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class TranscriptFinalPayload(TranscriptInterimPayload):
    utterance_id: UUID


class TranscriptInterim(EventEnvelope):
    """Transient WebSocket update."""

    event_type: Literal["transcript.interim"]
    payload: TranscriptInterimPayload


class TranscriptFinal(EventEnvelope):
    event_type: Literal["transcript.final"]
    payload: TranscriptFinalPayload


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
