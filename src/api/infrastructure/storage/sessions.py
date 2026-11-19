from itertools import groupby
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from api.application.ports import (
    SessionDetails,
    SessionReport,
    SessionTranscript,
    StoredRecommendation,
    StoredUtterance,
)
from api.domain.enums import SessionStatus
from api.domain.session import Session
from api.infrastructure.storage.schema import (
    recommendations,
    session_summaries,
    sessions,
    utterances,
)


class PostgresSessionRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def create(self, session: Session) -> None:
        async with self._session_factory.begin() as db:
            await db.execute(
                sessions.insert().values(id=session.id, status=session.status.value)
            )

    async def get(self, session_id: UUID) -> SessionDetails | None:
        summary_exists = (
            sa.select(session_summaries.c.session_id)
            .where(session_summaries.c.session_id == sessions.c.id)
            .exists()
        )
        query = sa.select(sessions, summary_exists.label("summary_available")).where(
            sessions.c.id == session_id
        )
        async with self._session_factory() as db:
            row = (await db.execute(query)).one_or_none()

        if row is None:
            return None
        return SessionDetails(
            session_id=row.id,
            status=SessionStatus(row.status),
            created_at=row.created_at,
            started_at=row.started_at,
            ended_at=row.ended_at,
            summary_available=row.summary_available,
        )

    async def get_transcript(self, session_id: UUID) -> SessionTranscript | None:
        query = (
            sa.select(
                utterances.c.id.label("utterance_id"),
                utterances.c.sequence,
                utterances.c.start_ms,
                utterances.c.end_ms,
                utterances.c.text,
                recommendations.c.id.label("recommendation_id"),
                recommendations.c.context_version,
                recommendations.c.action,
                recommendations.c.rationale,
                recommendations.c.faq_ids,
                recommendations.c.prompt_version,
            )
            .select_from(
                sessions.outerjoin(utterances).outerjoin(
                    recommendations,
                    sa.and_(
                        recommendations.c.session_id == utterances.c.session_id,
                        recommendations.c.utterance_id == utterances.c.id,
                    ),
                )
            )
            .where(sessions.c.id == session_id)
            .order_by(utterances.c.sequence, recommendations.c.context_version)
        )
        async with self._session_factory() as db:
            rows = (await db.execute(query)).all()

        if not rows:
            return None

        transcript = []
        for utterance_id, group in groupby(rows, key=lambda row: row.utterance_id):
            if utterance_id is None:
                continue
            utterance_rows = list(group)
            first = utterance_rows[0]
            transcript.append(
                StoredUtterance(
                    utterance_id=utterance_id,
                    sequence=first.sequence,
                    start_ms=first.start_ms,
                    end_ms=first.end_ms,
                    text=first.text,
                    recommendations=tuple(
                        StoredRecommendation(
                            recommendation_id=row.recommendation_id,
                            context_version=row.context_version,
                            action=row.action,
                            rationale=row.rationale,
                            faq_ids=tuple(row.faq_ids),
                            prompt_version=row.prompt_version,
                        )
                        for row in utterance_rows
                        if row.recommendation_id is not None
                    ),
                )
            )
        return SessionTranscript(session_id=session_id, utterances=tuple(transcript))

    async def get_report(self, session_id: UUID) -> SessionReport | None:
        query = (
            sa.select(session_summaries.c.summary, session_summaries.c.created_at)
            .select_from(sessions.outerjoin(session_summaries))
            .where(sessions.c.id == session_id)
        )
        async with self._session_factory() as db:
            row = (await db.execute(query)).one_or_none()

        if row is None:
            return None
        return SessionReport(
            session_id=session_id,
            summary=row.summary,
            summary_created_at=row.created_at,
        )
