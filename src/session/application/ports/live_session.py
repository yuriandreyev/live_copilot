from typing import Protocol
from uuid import UUID

from session.application.ports import SessionDetails
from session.domain.enums import SessionStatus


class LiveSessionStore(Protocol):
    async def get(self, session_id: UUID) -> SessionDetails | None: ...
    async def transition(
        self, session_id: UUID, previous: SessionStatus, target: SessionStatus
    ) -> bool: ...
