from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, TypeAdapter

from copilot_contracts.types import Contract, NonBlank, PositiveSequence


class IdentifiedContext(Contract):
    status: Literal["identified"]
    issue: NonBlank
    intent: NonBlank
    confidence: Annotated[float, Field(strict=True, ge=0, le=1)]


class InsufficientContext(Contract):
    status: Literal["insufficient_context"]


type AgentContext = Annotated[
    IdentifiedContext | InsufficientContext, Field(discriminator="status")
]
agent_context_adapter: TypeAdapter[AgentContext] = TypeAdapter(AgentContext)


class Recommendation(Contract):
    recommendation_id: UUID
    utterance_id: UUID
    context_version: PositiveSequence
    action: NonBlank
    rationale: NonBlank
    faq_ids: tuple[NonBlank, ...] = ()
    prompt_version: NonBlank
