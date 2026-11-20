from typing import Annotated, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]

Milliseconds = Annotated[int, Field(strict=True, ge=0)]
SAMPLE_RATE = 16_000
SAMPLE_BYTES = 2


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class TranscriptWindow(_Model):
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
