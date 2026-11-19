from datetime import UTC, datetime
from typing import Annotated

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
)

PositiveSequence = Annotated[int, Field(strict=True, gt=0)]
NonBlank = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def _to_utc(value: datetime) -> datetime:
    return value.astimezone(UTC)


UtcTimestamp = Annotated[AwareDatetime, AfterValidator(_to_utc)]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
