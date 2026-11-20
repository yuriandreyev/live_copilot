import argparse
import asyncio
from pathlib import Path
from wave import open as open_wave

from transcription.domain.entities import SAMPLE_BYTES, SAMPLE_RATE, FinalizedUtterance
from transcription.infrastructure.audio.faster_whisper import FasterWhisper


async def smoke(wav_path: Path, model_path: Path, language: str) -> None:
    model = FasterWhisper(
        model_path, device="cpu", compute_type="int8", language=language
    )
    try:
        recognizer = model.new_recognizer()
        interim_count = 0
        final_count = 0
        with open_wave(str(wav_path), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate()) != (
                1,
                SAMPLE_BYTES,
                SAMPLE_RATE,
            ):
                raise ValueError("Expected a mono 16 kHz PCM16 WAV file.")
            while frame := audio.readframes(SAMPLE_RATE // 10):
                result = await recognizer.accept_frame(frame)
                if isinstance(result, FinalizedUtterance):
                    final_count += 1
                    print(
                        f"final   {result.start_ms:>5}–{result.end_ms:<5} ms {result.text}"
                    )
                elif result is not None:
                    interim_count += 1
                    print(
                        f"interim {result.start_ms:>5}–{result.end_ms:<5} ms {result.text}"
                    )
        final = await recognizer.finish()
        if final is not None:
            final_count += 1
            print(f"final   {final.start_ms:>5}–{final.end_ms:<5} ms {final.text}")
        if not interim_count or not final_count:
            raise RuntimeError(
                f"Expected interim and final results, got {interim_count} and {final_count}."
            )
    finally:
        model.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Transcribe a local speech fixture with faster-whisper."
    )
    parser.add_argument("wav", type=Path)
    parser.add_argument(
        "--model", type=Path, default=Path("models/faster-whisper-small")
    )
    parser.add_argument("--language", default="ru")
    args = parser.parse_args()
    asyncio.run(smoke(args.wav, args.model, args.language))
