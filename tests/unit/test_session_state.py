from itertools import product

import pytest

from api.domain.enums import SessionStatus
from api.domain.session import InvalidSessionTransition, Session

REACHABLE_PATHS = {
    SessionStatus.CREATED: (),
    SessionStatus.LIVE: (SessionStatus.LIVE,),
    SessionStatus.STOPPING: (SessionStatus.LIVE, SessionStatus.STOPPING),
    SessionStatus.COMPLETED: (
        SessionStatus.LIVE,
        SessionStatus.STOPPING,
        SessionStatus.COMPLETED,
    ),
    SessionStatus.INTERRUPTED: (SessionStatus.LIVE, SessionStatus.INTERRUPTED),
    SessionStatus.FAILED: (SessionStatus.LIVE, SessionStatus.FAILED),
}
LEGAL_TRANSITIONS = {
    (SessionStatus.CREATED, SessionStatus.LIVE),
    (SessionStatus.LIVE, SessionStatus.STOPPING),
    (SessionStatus.STOPPING, SessionStatus.COMPLETED),
    (SessionStatus.LIVE, SessionStatus.INTERRUPTED),
    (SessionStatus.LIVE, SessionStatus.FAILED),
    (SessionStatus.STOPPING, SessionStatus.INTERRUPTED),
    (SessionStatus.STOPPING, SessionStatus.FAILED),
}


@pytest.mark.parametrize(("source", "target"), product(SessionStatus, repeat=2))
def test_transition_matrix(source: SessionStatus, target: SessionStatus) -> None:
    session = Session()
    for status in REACHABLE_PATHS[source]:
        session.transition_to(status)
    original_id = session.id
    original_sequence = session.next_sequence()

    if (source, target) in LEGAL_TRANSITIONS:
        session.transition_to(target)
        assert session.status is target
    else:
        with pytest.raises(
            InvalidSessionTransition, match=f"from {source} to {target}"
        ):
            session.transition_to(target)
        assert session.status is source

    assert session.id == original_id
    assert session.sequence == original_sequence


def test_sequences_increase_independently_per_session() -> None:
    first, second = Session(), Session()

    assert first.id != second.id
    assert first.next_sequence() == second.next_sequence() == 1
    first.transition_to(SessionStatus.LIVE)
    assert first.next_sequence() == 2
    assert second.sequence == 1
