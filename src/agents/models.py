from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, TypeAdapter

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
PositiveSequence = Annotated[int, Field(strict=True, gt=0)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IdentifiedContext(_Model):
    status: Literal["identified"]
    issue: NonBlank
    intent: NonBlank
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)]


class InsufficientContext(_Model):
    status: Literal["insufficient_context"]


type AgentContext = Annotated[
    IdentifiedContext | InsufficientContext, Field(discriminator="status")
]
agent_context_adapter: TypeAdapter[AgentContext] = TypeAdapter(AgentContext)


class Recommendation(_Model):
    recommendation_id: UUID
    utterance_id: UUID
    context_version: PositiveSequence
    action: NonBlank
    rationale: NonBlank
    faq_ids: tuple[NonBlank, ...] = ()
    prompt_version: NonBlank
