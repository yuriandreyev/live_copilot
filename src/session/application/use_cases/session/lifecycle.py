from uuid import UUID

from session.application.ports.live_session import LiveSessionStore
from session.domain.enums import SessionStatus
from session.domain.session import validate_transition


class SessionLifecycle:
    def __init__(self, store: LiveSessionStore) -> None:
        self._store = store

    async def get_status(self, session_id: UUID) -> SessionStatus | None:
        details = await self._store.get(session_id)
        return details.status if details is not None else None

    async def transition(
        self, session_id: UUID, previous: SessionStatus, target: SessionStatus
    ) -> bool:
        validate_transition(previous, target)
        return await self._store.transition(session_id, previous, target)
