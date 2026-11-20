from typing import Protocol

from transcription.domain.entities import FinalizedUtterance, TranscriptWindow


class SpeechRecognizer(Protocol):
    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None:
        """Return a partial result or a FinalizedUtterance when speech ends."""
        ...

    async def finish(self) -> FinalizedUtterance | None: ...
