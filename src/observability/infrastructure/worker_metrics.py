import asyncio
import json
from pathlib import Path

_OUTCOMES = ("processed", "duplicate", "retried", "failed")


class WorkerMetrics:
    """Fixed-size snapshot shared by the single worker and API on this host."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._counts = self._read()

    def _read(self) -> dict[str, int]:
        try:
            values = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(values, dict):
            return {}
        return {
            key: values[key]
            for key in _OUTCOMES
            if type(values.get(key)) is int and values[key] >= 0
        }

    async def read(self) -> dict[str, int]:
        return await asyncio.to_thread(self._read)

    async def record(self, outcome: str) -> None:
        self._counts[outcome] = self._counts.get(outcome, 0) + 1
        await asyncio.to_thread(self._write, dict(self._counts))

    def _write(self, counts: dict[str, int]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        try:
            temporary.write_text(json.dumps(counts), encoding="utf-8")
            temporary.replace(self._path)
        finally:
            temporary.unlink(missing_ok=True)
