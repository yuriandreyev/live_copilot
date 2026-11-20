import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from agents.public import Recommendation, agent_context_adapter
from workflows.live_capture.infrastructure.events import (
    CaptureStart,
    CaptureStop,
    RecommendationCreated,
    TranscriptFinal,
    TranscriptFinalPayload,
    TranscriptInterim,
    client_command_adapter,
    durable_event_adapter,
    server_event_adapter,
)

SESSION_ID = UUID("9091cdd0-474b-48fb-b37e-e827a5a49c90")
UTTERANCE_ID = UUID("63b54e4d-95f1-49a5-825e-659d8d50fc2a")


@pytest.fixture
def transcript_final() -> TranscriptFinal:
    return TranscriptFinal(
        schema_version=1,
        event_type="transcript.final",
        event_id=UUID("d60e6f4e-2f6f-47f6-852a-894aac3f9b82"),
        correlation_id=SESSION_ID,
        session_id=SESSION_ID,
        sequence=12,
        occurred_at=datetime(2026, 11, 18, 8, tzinfo=UTC),
        payload=TranscriptFinalPayload(
            utterance_id=UTTERANCE_ID,
            start_ms=8100,
            end_ms=12700,
            text="Customers are receiving duplicate API notifications.",
        ),
    )


def test_final_transcript_round_trips_through_both_contracts(
    transcript_final: TranscriptFinal,
) -> None:
    serialized = transcript_final.model_dump_json()

    assert server_event_adapter.validate_json(serialized) == transcript_final
    assert durable_event_adapter.validate_json(serialized) == transcript_final
    assert json.loads(serialized) == {
        "schema_version": 1,
        "event_id": "d60e6f4e-2f6f-47f6-852a-894aac3f9b82",
        "event_type": "transcript.final",
        "session_id": str(SESSION_ID),
        "sequence": 12,
        "occurred_at": "2026-11-18T08:00:00Z",
        "correlation_id": str(SESSION_ID),
        "payload": {
            "utterance_id": str(UTTERANCE_ID),
            "start_ms": 8100,
            "end_ms": 12700,
            "text": "Customers are receiving duplicate API notifications.",
        },
    }


def test_recommendation_serializes_with_utterance_and_context(
    transcript_final: TranscriptFinal,
) -> None:
    recommendation_id = UUID("7af3db01-ec4c-4816-801b-d2447addd990")
    event = RecommendationCreated(
        schema_version=1,
        event_type="recommendation.created",
        event_id=uuid4(),
        session_id=transcript_final.session_id,
        correlation_id=transcript_final.correlation_id,
        sequence=13,
        occurred_at=transcript_final.occurred_at,
        payload=Recommendation(
            recommendation_id=recommendation_id,
            utterance_id=UTTERANCE_ID,
            context_version=1,
            action="Check whether retries carry the same event ID.",
            rationale="Repeated deliveries can arrive after a retry.",
            faq_ids=("event-retries",),
            prompt_version="1",
        ),
    )

    serialized = event.model_dump_json()

    assert durable_event_adapter.validate_json(serialized) == event
    assert server_event_adapter.validate_json(serialized) == event
    assert json.loads(serialized)["payload"] == {
        "recommendation_id": str(recommendation_id),
        "utterance_id": str(UTTERANCE_ID),
        "context_version": 1,
        "action": "Check whether retries carry the same event ID.",
        "rationale": "Repeated deliveries can arrive after a retry.",
        "faq_ids": ["event-retries"],
        "prompt_version": "1",
    }


@pytest.mark.parametrize(
    ("name", "command"),
    [("capture.start", CaptureStart), ("capture.stop", CaptureStop)],
)
def test_client_command_uses_typed_discriminator(
    name: str, command: type[CaptureStart] | type[CaptureStop]
) -> None:
    data = {"schema_version": 1, "event_type": name, "session_id": str(SESSION_ID)}

    assert isinstance(client_command_adapter.validate_python(data), command)

    with pytest.raises(ValidationError, match="extra_forbidden"):
        client_command_adapter.validate_python(
            {**data, "payload": {"unexpected": True}}
        )


@pytest.mark.parametrize("version", [2, "1", 1.0, True])
def test_invalid_schema_versions_fail(
    transcript_final: TranscriptFinal, version: object
) -> None:
    data = transcript_final.model_dump(mode="json")
    data["schema_version"] = version

    for adapter in (server_event_adapter, durable_event_adapter):
        with pytest.raises(ValidationError, match="schema_version"):
            adapter.validate_python(data)

    data = {
        "schema_version": version,
        "event_type": "capture.start",
        "session_id": str(SESSION_ID),
    }
    with pytest.raises(ValidationError, match="schema_version"):
        client_command_adapter.validate_python(data)


@pytest.mark.parametrize(
    ("field", "value", "error"),
    [
        ("utterance_id", "bad-uuid", "utterance_id"),
        ("start_ms", -1, "start_ms"),
        ("start_ms", 3.5, "start_ms"),
        ("end_ms", 8100, "end_ms must be greater than start_ms"),
        ("text", "  ", "text"),
    ],
)
def test_invalid_final_payload_fails(
    transcript_final: TranscriptFinal, field: str, value: object, error: str
) -> None:
    data = transcript_final.model_dump(mode="json")
    data["payload"][field] = value

    with pytest.raises(ValidationError, match=error):
        durable_event_adapter.validate_python(data)


@pytest.mark.parametrize("sequence", [0, -1, "12", True])
def test_event_sequence_must_be_a_positive_integer(
    transcript_final: TranscriptFinal, sequence: object
) -> None:
    data = transcript_final.model_dump(mode="json")
    data["sequence"] = sequence

    with pytest.raises(ValidationError, match="sequence"):
        server_event_adapter.validate_python(data)


def test_interim_events_are_websocket_only(transcript_final: TranscriptFinal) -> None:
    data = transcript_final.model_dump(mode="json")
    data["event_type"] = "transcript.interim"
    del data["payload"]["utterance_id"]

    assert isinstance(server_event_adapter.validate_python(data), TranscriptInterim)
    with pytest.raises(ValidationError, match="union_tag_invalid"):
        durable_event_adapter.validate_python(data)


def test_timestamps_require_timezone_and_serialize_as_utc(
    transcript_final: TranscriptFinal,
) -> None:
    data = transcript_final.model_dump(mode="json")
    data["occurred_at"] = "2026-11-18T15:00:00+07:00"

    assert server_event_adapter.validate_python(data).model_dump(mode="json")[
        "occurred_at"
    ] == ("2026-11-18T08:00:00Z")

    data["occurred_at"] = "2026-11-18T08:00:00"
    with pytest.raises(ValidationError, match="timezone"):
        server_event_adapter.validate_python(data)


def test_agent_context_accepts_fallback_and_validates_confidence() -> None:
    fallback = agent_context_adapter.validate_python({"status": "insufficient_context"})
    assert fallback.status == "insufficient_context"

    identified = {
        "status": "identified",
        "issue": "duplicate notifications",
        "intent": "diagnose retries",
        "confidence": 0.8,
    }
    assert agent_context_adapter.validate_python(identified).status == "identified"
    with pytest.raises(ValidationError, match="confidence"):
        agent_context_adapter.validate_python({**identified, "confidence": 1.2})
