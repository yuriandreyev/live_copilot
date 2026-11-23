import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest

from worker.application.ports.delivery import (
    Delivery,
    InvalidEvent,
    ProcessingUnavailable,
    SessionEvent,
)
from worker.application.use_cases.process_events import ProcessEvents


class Consumer:
    @asynccontextmanager
    async def deliveries(self) -> AsyncIterator[AsyncIterator[Delivery]]:
        raise AssertionError("This test processes one delivery directly.")
        yield  # pragma: no cover


@pytest.mark.parametrize(
    ("failures", "valid", "expected"),
    [
        (0, True, ["commit", "ack"]),
        (2, True, ["retry", "retry", "commit", "ack"]),
        (3, True, ["retry", "retry", "retry", "dead"]),
        (0, False, ["dead"]),
    ],
)
def test_worker_acknowledges_commit_and_bounds_retries(
    failures: int, valid: bool, expected: list[str]
) -> None:
    steps: list[str] = []
    event = SessionEvent(uuid4(), uuid4(), "session.completed")

    class Store:
        async def apply(
            self,
            delivered: SessionEvent,
            *,
            summarize: Callable[[int, int], str] | None,
        ) -> None:
            assert delivered == event
            assert summarize is not None and summarize(1, 2) == (
                "Finalized utterances: 1. Recommendations: 2."
            )
            if len(steps) < failures:
                steps.append("retry")
                raise ProcessingUnavailable
            steps.append("commit")

    class Message:
        def event(self) -> SessionEvent:
            if not valid:
                raise InvalidEvent
            return event

        async def ack(self) -> None:
            steps.append("ack")

        async def dead_letter(self) -> None:
            steps.append("dead")

    asyncio.run(ProcessEvents(Consumer(), Store()).process(Message()))
    assert steps == expected
