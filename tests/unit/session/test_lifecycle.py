import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from session.application.ports.live_session import LiveSessionStore
from session.domain.session import InvalidSessionTransition
from session.public import SessionLifecycle, SessionStatus


def test_lifecycle_rejects_invalid_transition_before_persisting() -> None:
    store = AsyncMock(spec=LiveSessionStore)
    lifecycle = SessionLifecycle(store)

    with pytest.raises(InvalidSessionTransition):
        asyncio.run(
            lifecycle.transition(
                uuid4(), SessionStatus.CREATED, SessionStatus.COMPLETED
            )
        )

    store.transition.assert_not_awaited()
