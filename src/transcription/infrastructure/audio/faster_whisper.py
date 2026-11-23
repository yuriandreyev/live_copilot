import asyncio
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import numpy as np
from faster_whisper import WhisperModel  # type: ignore[import-untyped]

from transcription.application.utterance_assembler import (
    AudioWindow,
    UtteranceAssembler,
)
from transcription.domain.entities import FinalizedUtterance, TranscriptWindow


class FasterWhisperRecognizer:
    def __init__(
        self,
        infer: Callable[[bytes], str],
        executor: ThreadPoolExecutor,
        capacity: asyncio.Lock | None = None,
    ) -> None:
        self._infer = infer
        self._executor = executor
        self._capacity = capacity if capacity is not None else asyncio.Lock()
        self._assembler = UtteranceAssembler()

    async def accept_frame(self, frame: bytes) -> TranscriptWindow | None:
        return await self._recognize(self._assembler.accept(frame))

    async def finish(self) -> FinalizedUtterance | None:
        result = await self._recognize(self._assembler.finish())
        assert result is None or isinstance(result, FinalizedUtterance)
        return result

    async def _recognize(self, window: AudioWindow | None) -> TranscriptWindow | None:
        if window is None or window.end_ms <= window.start_ms:
            return None
        loop = asyncio.get_running_loop()
        await self._capacity.acquire()
        try:
            inference = loop.run_in_executor(self._executor, self._infer, window.pcm)
        except RuntimeError:
            self._capacity.release()
            raise

        def release(done: asyncio.Future[str]) -> None:
            self._capacity.release()
            if not done.cancelled():
                done.exception()

        # Timed-out callers leave at most one native inference in flight.
        inference.add_done_callback(release)
        text = (await asyncio.shield(inference)).strip()
        if not text:
            return None
        if window.final:
            return FinalizedUtterance(
                start_ms=window.start_ms,
                end_ms=window.end_ms,
                text=text,
                utterance_id=uuid4(),
            )
        return TranscriptWindow(
            start_ms=window.start_ms, end_ms=window.end_ms, text=text
        )


class FasterWhisper:
    def __init__(
        self, model_path: Path, *, device: str, compute_type: str, language: str | None
    ) -> None:
        if not model_path.is_dir():
            raise FileNotFoundError(f"ASR model directory does not exist: {model_path}")
        for name in ("config.json", "model.bin", "tokenizer.json"):
            if not (model_path / name).is_file():
                raise FileNotFoundError(
                    f"ASR model file does not exist: {model_path / name}"
                )
        self._model = WhisperModel(
            str(model_path),
            device=device,
            compute_type=compute_type,
            local_files_only=True,
        )
        self._language = None if language == "auto" else language
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="asr")
        self._capacity = asyncio.Lock()

    def new_recognizer(self) -> FasterWhisperRecognizer:
        return FasterWhisperRecognizer(self._transcribe, self._executor, self._capacity)

    def close(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _transcribe(self, pcm: bytes) -> str:
        audio = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768
        segments, _ = self._model.transcribe(
            audio,
            language=self._language,
            beam_size=1,
            condition_on_previous_text=False,
        )
        return " ".join(segment.text.strip() for segment in segments)
