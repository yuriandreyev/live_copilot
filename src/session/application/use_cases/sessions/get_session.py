from uuid import UUID

from session.application.ports import SessionDetails, SessionRepository
from session.application.use_cases.sessions.errors import SessionNotFound


class GetSession:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def execute(self, session_id: UUID) -> SessionDetails:
        result = await self._repository.get(session_id)
        if result is None:
            raise SessionNotFound(session_id)
        return result
