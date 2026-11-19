from api.application.ports import SessionRepository
from api.domain.session import Session


class CreateSession:
    def __init__(self, repository: SessionRepository) -> None:
        self._repository = repository

    async def execute(self) -> Session:
        session = Session()
        await self._repository.create(session)
        return session
