import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import get_ident
from wave import open as open_wave

from transcription.application.utterance_assembler import UtteranceAssembler
from transcription.infrastructure.audio.faster_whisper import FasterWhisperRecognizer
from transcription.public import SAMPLE_RATE, FinalizedUtterance, TranscriptWindow

FRAME_SAMPLES = SAMPLE_RATE // 10
SILENCE = b"\x00\x00" * FRAME_SAMPLES
SPEECH = b"\x00\x10" * FRAME_SAMPLES


def test_wav_fixture_finalizes_after_silence_without_repeating_interim(
    tmp_path: Path,
) -> None:
    wav_path = tmp_path / "capture.wav"
    with open_wave(str(wav_path), "wb") as audio:
        audio.setparams((1, 2, SAMPLE_RATE, 0, "NONE", "not compressed"))
        audio.writeframes(SILENCE * 4 + SPEECH * 32 + SILENCE * 8 + SPEECH * 2)

    caller_thread = get_ident()

    def infer(pcm: bytes) -> str:
        assert get_ident() != caller_thread
        assert pcm == SPEECH * (len(pcm) // len(SPEECH))
        return "Привет"

    async def recognize(executor: ThreadPoolExecutor) -> list[TranscriptWindow]:
        recognizer = FasterWhisperRecognizer(infer, executor)
        results: list[TranscriptWindow] = []
        with open_wave(str(wav_path), "rb") as audio:
            while frame := audio.readframes(FRAME_SAMPLES):
                result = await recognizer.accept_frame(frame)
                if result is not None:
                    results.append(result)
        final = await recognizer.finish()
        assert final is not None
        results.append(final)
        assert await recognizer.finish() is None
        return results

    with ThreadPoolExecutor(max_workers=1) as executor:
        interim, final, last = asyncio.run(recognize(executor))
    assert type(interim) is TranscriptWindow
    assert (interim.start_ms, interim.end_ms, interim.text) == (400, 3400, "Привет")
    assert isinstance(final, FinalizedUtterance)
    assert isinstance(last, FinalizedUtterance)
    assert (final.start_ms, final.end_ms) == (400, 3600)
    assert (last.start_ms, last.end_ms) == (4400, 4600)
    assert final.utterance_id != last.utterance_id


def test_silence_never_invokes_inference() -> None:
    def infer(_pcm: bytes) -> str:
        raise AssertionError("Silence reached the recognition model")

    async def recognize(executor: ThreadPoolExecutor) -> None:
        recognizer = FasterWhisperRecognizer(infer, executor)
        for _ in range(130):
            assert await recognizer.accept_frame(SILENCE) is None
        assert await recognizer.finish() is None

    with ThreadPoolExecutor(max_workers=1) as executor:
        asyncio.run(recognize(executor))


def test_utterance_is_finalized_at_maximum_length() -> None:
    assembler = UtteranceAssembler()
    windows = [
        window for _ in range(120) if (window := assembler.accept(SPEECH)) is not None
    ]
    assert [(window.end_ms, window.final) for window in windows] == [
        (3000, False),
        (6000, False),
        (9000, False),
        (12000, True),
    ]
    assert assembler.finish() is None
