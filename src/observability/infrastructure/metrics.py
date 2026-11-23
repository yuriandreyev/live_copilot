from collections import Counter
from dataclasses import dataclass, field
from threading import Lock

_BUCKETS = (0.1, 0.25, 0.5, 1, 2, 5, 10, 20)


@dataclass
class _Histogram:
    counts: list[int] = field(default_factory=lambda: [0] * len(_BUCKETS))
    count: int = 0
    total: float = 0

    def observe(self, seconds: float) -> None:
        self.count += 1
        self.total += seconds
        for i, upper in enumerate(_BUCKETS):
            if seconds <= upper:
                self.counts[i] += 1

    def render(self, name: str) -> list[str]:
        buckets = [
            f'{name}_bucket{{le="{bound}"}} {count}'
            for bound, count in zip(_BUCKETS, self.counts, strict=True)
        ]
        return [
            f"# TYPE {name} histogram",
            *buckets,
            f'{name}_bucket{{le="+Inf"}} {self.count}',
            f"{name}_sum {self.total}",
            f"{name}_count {self.count}",
        ]


class Metrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._gauges: dict[str, float] = {
            "live_sessions": 0,
            "audio_buffer_seconds": 0,
            "audio_queue_depth": 0,
        }
        self._counts: Counter[tuple[str, str]] = Counter()
        self._histograms = {
            "asr_finalization_seconds": _Histogram(),
            "recommendation_seconds": _Histogram(),
        }

    def gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def increment(self, name: str, outcome: str = "") -> None:
        with self._lock:
            self._counts[name, outcome] += 1

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            self._histograms[name].observe(seconds)

    def render(self, pending: int | None, worker: dict[str, int]) -> str:
        with self._lock:
            gauges = dict(self._gauges)
            if pending is not None:
                gauges["outbox_pending_events"] = pending
            else:
                gauges["outbox_pending_events"] = float("nan")
            lines = [
                line
                for name, value in gauges.items()
                for line in (
                    f"# TYPE {name} gauge",
                    f"{name} {value if value == value else 'NaN'}",
                )
            ]
            counters = (
                ("ws_disconnects_total", ("",)),
                (
                    "capture_errors_total",
                    tuple(
                        sorted(
                            failure
                            for metric, failure in self._counts
                            if metric == "capture_errors_total"
                        )
                    ),
                ),
                (
                    "llm_requests_total",
                    ("success", "timeout", "validation_error", "unavailable"),
                ),
                (
                    "worker_events_total",
                    ("processed", "duplicate", "retried", "failed"),
                ),
            )
            for name, outcomes in counters:
                lines.append(f"# TYPE {name} counter")
                for outcome in outcomes:
                    labels = f'{{outcome="{outcome}"}}' if outcome else ""
                    value = (
                        worker.get(outcome, 0)
                        if name == "worker_events_total"
                        else self._counts[name, outcome]
                    )
                    lines.append(f"{name}{labels} {value}")
            for name, histogram in self._histograms.items():
                lines.extend(histogram.render(name))
            return "\n".join(lines) + "\n"
