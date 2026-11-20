from uuid import uuid4

from api.application.audio import SAMPLE_BYTES, SAMPLE_RATE
from copilot_contracts.events import FinalizedUtterance, TranscriptWindow

FAKE_TEXT = "Simulated transcript"


class FakeSpeechRecognizer:
    def __init__(self) -> None:
        self._bytes_received = 0

    @property
    def _duration_ms(self) -> int:
        return self._bytes_received * 1000 // (SAMPLE_RATE * SAMPLE_BYTES)

    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None:
        previous_duration = self._duration_ms
        self._bytes_received += len(frame)
        if self._duration_ms == previous_duration:
            return None
        return TranscriptWindow(start_ms=0, end_ms=self._duration_ms, text=FAKE_TEXT)

    async def finish(self) -> FinalizedUtterance | None:
        if not self._duration_ms:
            return None
        return FinalizedUtterance(
            utterance_id=uuid4(), start_ms=0, end_ms=self._duration_ms, text=FAKE_TEXT
        )
