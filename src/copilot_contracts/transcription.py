from typing import Annotated, Self
from uuid import UUID

from pydantic import Field, model_validator

from copilot_contracts.types import Contract, NonBlank

Milliseconds = Annotated[int, Field(strict=True, ge=0)]


class TranscriptWindow(Contract):
    start_ms: Milliseconds
    end_ms: Milliseconds
    text: NonBlank

    @model_validator(mode="after")
    def validate_audio_window(self) -> Self:
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms")
        return self


class FinalizedUtterance(TranscriptWindow):
    utterance_id: UUID
