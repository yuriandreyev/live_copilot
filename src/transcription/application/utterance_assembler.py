from array import array
from dataclasses import dataclass
from sys import byteorder

from transcription.domain.entities import SAMPLE_BYTES, SAMPLE_RATE

_BYTES_PER_SECOND = SAMPLE_RATE * SAMPLE_BYTES
_SILENCE_BYTES = _BYTES_PER_SECOND * 700 // 1000
_INTERIM_BYTES = _BYTES_PER_SECOND * 3
_MAX_UTTERANCE_BYTES = _BYTES_PER_SECOND * 12
_SPEECH_RMS = 300


@dataclass(frozen=True)
class AudioWindow:
    pcm: bytes
    start_ms: int
    end_ms: int
    final: bool


def _contains_speech(frame: bytes) -> bool:
    samples = array("h", frame)
    if byteorder == "big":
        samples.byteswap()
    return sum(sample * sample for sample in samples) >= len(samples) * _SPEECH_RMS**2


class UtteranceAssembler:
    def __init__(self) -> None:
        self._offset = 0
        self._start = 0
        self._pcm = bytearray()
        self._voiced_end = 0
        self._next_interim = _INTERIM_BYTES

    def accept(self, frame: bytes) -> AudioWindow | None:
        if not frame or len(frame) % SAMPLE_BYTES:
            raise ValueError("Expected non-empty PCM16 samples.")
        start = self._offset
        self._offset += len(frame)
        voiced = _contains_speech(frame)
        if not self._pcm:
            if not voiced:
                return None
            self._start = start

        self._pcm.extend(frame)
        if voiced:
            self._voiced_end = len(self._pcm)
        if (
            len(self._pcm) >= _MAX_UTTERANCE_BYTES
            or len(self._pcm) - self._voiced_end >= _SILENCE_BYTES
        ):
            return self.finish()
        if self._voiced_end >= self._next_interim:
            self._next_interim += _INTERIM_BYTES
            return self._window(final=False)
        return None

    def finish(self) -> AudioWindow | None:
        if not self._pcm:
            return None
        window = self._window(final=True)
        self._pcm.clear()
        self._voiced_end = 0
        self._next_interim = _INTERIM_BYTES
        return window

    def _window(self, *, final: bool) -> AudioWindow:
        return AudioWindow(
            pcm=bytes(self._pcm[: self._voiced_end]),
            start_ms=self._start * 1000 // _BYTES_PER_SECOND,
            end_ms=(self._start + self._voiced_end) * 1000 // _BYTES_PER_SECOND,
            final=final,
        )
