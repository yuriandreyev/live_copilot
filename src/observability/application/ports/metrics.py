from typing import Protocol


class MetricsView(Protocol):
    def render(self, pending: int | None, worker: dict[str, int]) -> str: ...
