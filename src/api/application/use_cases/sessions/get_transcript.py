from uuid import UUID

from api.application.ports import SessionRepository, SessionTranscript
from api.application.use_cases.sessions.errors import SessionNotFound


class GetTranscript:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def execute(self, session_id: UUID) -> SessionTranscript:
        result = await self._repository.get_transcript(session_id)
        if result is None:
            raise SessionNotFound(session_id)
        return result
