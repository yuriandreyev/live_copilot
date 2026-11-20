import pytest
from pydantic import ValidationError

from transcription.public import TranscriptWindow


def test_transcript_window_requires_end_after_start() -> None:
    with pytest.raises(ValidationError, match="end_ms must be greater than start_ms"):
        TranscriptWindow(start_ms=100, end_ms=100, text="Transcript")
