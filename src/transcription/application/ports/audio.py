from typing import Protocol

from copilot_contracts.events import FinalizedUtterance, TranscriptWindow

SAMPLE_RATE = 16_000
SAMPLE_BYTES = 2


class SpeechRecognizer(Protocol):
    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None: ...
    async def finish(self) -> FinalizedUtterance | None: ...
