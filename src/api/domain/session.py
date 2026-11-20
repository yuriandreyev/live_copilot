from uuid import UUID, uuid4

from api.domain.enums import SessionStatus

_ALLOWED_TRANSITIONS = {
    SessionStatus.CREATED: frozenset({SessionStatus.LIVE}),
    SessionStatus.LIVE: frozenset(
        {SessionStatus.STOPPING, SessionStatus.INTERRUPTED, SessionStatus.FAILED}
    ),
    SessionStatus.STOPPING: frozenset(
        {SessionStatus.COMPLETED, SessionStatus.INTERRUPTED, SessionStatus.FAILED}
    ),
    SessionStatus.COMPLETED: frozenset(),
    SessionStatus.INTERRUPTED: frozenset(),
    SessionStatus.FAILED: frozenset(),
}


class InvalidSessionTransition(ValueError):
    pass


class Session:
    def __init__(self, session_id: UUID | None = None) -> None:
        self._id = session_id if session_id is not None else uuid4()
        self._status = SessionStatus.CREATED
        self._sequence = 0

    @property
    def id(self) -> UUID:
        return self._id

    @property
    def status(self) -> SessionStatus:
        return self._status

    @property
    def sequence(self) -> int:
        return self._sequence

    def transition_to(self, status: SessionStatus) -> None:
        if (
            not isinstance(status, SessionStatus)
            or status not in _ALLOWED_TRANSITIONS[self.status]
        ):
            raise InvalidSessionTransition(
                f"Cannot transition from {self.status} to {status}"
            )
        self._status = status

    def next_sequence(self) -> int:
        """Allocate the next server event sequence for this session."""
        self._sequence += 1
        return self._sequence
