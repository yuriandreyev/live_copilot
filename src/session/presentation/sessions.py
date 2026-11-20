from uuid import UUID

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from session.application.ports import SessionDetails, SessionReport, SessionTranscript
from session.application.use_cases.session.create_session import CreateSession
from session.application.use_cases.session.errors import SessionNotFound
from session.application.use_cases.session.get_report import GetReport
from session.application.use_cases.session.get_session import GetSession
from session.application.use_cases.session.get_transcript import GetTranscript
from session.domain.enums import SessionStatus


class SessionCreated(BaseModel):
    session_id: UUID
    status: SessionStatus


def register_session_routes(
    app: FastAPI,
    *,
    create_session_use_case: CreateSession,
    get_session_use_case: GetSession,
    get_transcript_use_case: GetTranscript,
    get_report_use_case: GetReport,
) -> None:
    router = APIRouter(prefix="/api/sessions", tags=["sessions"])

    @app.exception_handler(SessionNotFound)
    async def session_not_found(
        _request: Request, _error: SessionNotFound
    ) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Session not found"})

    @router.post("", status_code=201)
    async def create_session() -> SessionCreated:
        session = await create_session_use_case.execute()
        return SessionCreated(session_id=session.id, status=session.status)

    @router.get("/{session_id}")
    async def get_session(session_id: UUID) -> SessionDetails:
        return await get_session_use_case.execute(session_id)

    @router.get("/{session_id}/transcript")
    async def get_transcript(session_id: UUID) -> SessionTranscript:
        return await get_transcript_use_case.execute(session_id)

    @router.get("/{session_id}/report")
    async def get_report(session_id: UUID) -> SessionReport:
        return await get_report_use_case.execute(session_id)

    app.include_router(router)
