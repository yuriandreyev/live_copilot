from typing import Protocol
from uuid import UUID

from api.application.ports import SessionDetails
from api.domain.enums import SessionStatus


class LiveSessionStore(Protocol):
    async def get(self, session_id: UUID) -> SessionDetails | None: ...
    async def transition(
        self, session_id: UUID, previous: SessionStatus, target: SessionStatus
    ) -> bool: ...
