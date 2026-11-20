from typing import Protocol

from transcription.application.models import FinalizedUtterance, TranscriptWindow


class SpeechRecognizer(Protocol):
    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None: ...
    async def finish(self) -> FinalizedUtterance | None: ...
