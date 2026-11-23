from uuid import UUID

from session.application.ports.capture_records import OutboxEvent
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
        self,
        session_id: UUID,
        previous: SessionStatus,
        target: SessionStatus,
        *,
        completion_event: OutboxEvent | None = None,
    ) -> bool:
        validate_transition(previous, target)
        if target is SessionStatus.COMPLETED:
            if (
                completion_event is None
                or completion_event.event_type != "session.completed"
            ):
                raise ValueError(
                    "A completed transition requires a session.completed event."
                )
        elif completion_event is not None:
            raise ValueError(
                "Only a completed transition may enqueue session.completed."
            )
        return await self._store.transition(
            session_id, previous, target, completion_event=completion_event
        )
