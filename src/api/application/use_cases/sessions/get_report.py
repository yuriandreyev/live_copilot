from uuid import UUID

from api.application.ports import SessionReport, SessionRepository
from api.application.use_cases.sessions.errors import SessionNotFound


class GetReport:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def execute(self, session_id: UUID) -> SessionReport:
        result = await self._repository.get_report(session_id)
        if result is None:
            raise SessionNotFound(session_id)
        return result
