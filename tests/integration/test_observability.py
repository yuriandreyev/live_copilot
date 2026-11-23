import asyncio
import json
from threading import Event
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from agents.infrastructure.llama_cpp import LlamaCpp
from bootstrap.main import create_app
from bootstrap.settings import Settings
from transcription.infrastructure.audio.fake_asr import FakeSpeechRecognizer
from transcription.public import FinalizedUtterance

_PRIVATE = "private transcript or credentials must stay out of logs"


@pytest.mark.parametrize("timeout", [False, True])
def test_readiness_metrics_and_correlated_logs_during_capture(
    database_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    timeout: bool,
) -> None:
    async def ready(self: LlamaCpp) -> bool:
        return not timeout

    async def complete(self: LlamaCpp, instructions: str, data: str) -> str:
        if timeout:
            raise TimeoutError(_PRIVATE)
        return '{"status":"insufficient_context"}'

    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr(LlamaCpp, "complete", complete)
    monkeypatch.setattr(LlamaCpp, "ready", ready)
    if timeout:
        monkeypatch.setenv("RABBITMQ_PORT", "1")
        monkeypatch.setenv("OUTBOX_ENABLED", "true")

    with TestClient(create_app()) as client:
        readiness = client.get("/readyz")
        assert readiness.status_code == (503 if timeout else 200)
        assert readiness.json()["dependencies"] == {
            "postgres": "ready",
            "asr": "ready",
            "rabbitmq": "unavailable" if timeout else "ready",
            "llm": "unavailable" if timeout else "ready",
        }
        assert client.get("/healthz").status_code == 200
        session_id = client.post("/api/sessions").json()["session_id"]
        command = {"schema_version": 1, "session_id": session_id}
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_json({**command, "event_type": "capture.start"})
            assert socket.receive_json()["payload"]["status"] == "live"
            assert "live_sessions 1\n" in client.get("/metrics").text
            socket.send_bytes(b"\x01\x00" * 1600)
            assert socket.receive_json()["event_type"] == "transcript.interim"
            socket.send_json({**command, "event_type": "capture.stop"})
            assert socket.receive_json()["payload"]["status"] == "stopping"
            final = socket.receive_json()
            assert final["event_type"] == "transcript.final"
            if not timeout:
                assert socket.receive_json()["event_type"] == "analysis.completed"
            recommendation = socket.receive_json()
            assert recommendation["event_type"] == "recommendation.created"
            if timeout:
                assert (
                    "Local AI analysis could not finish"
                    in recommendation["payload"]["rationale"]
                )
            assert socket.receive_json()["event_type"] == "session.completed"
        assert (
            client.get(f"/api/sessions/{session_id}/transcript").json()["utterances"][
                0
            ]["text"]
            == final["payload"]["text"]
        )
        metrics = client.get("/metrics")
        assert metrics.headers["content-type"].startswith("text/plain; version=0.0.4")
        outcome = "timeout" if timeout else "success"
        assert f'llm_requests_total{{outcome="{outcome}"}} 1\n' in metrics.text
        assert "asr_finalization_seconds_count 1\n" in metrics.text
        assert "recommendation_seconds_count 1\n" in metrics.text
        assert "live_sessions 0\n" in metrics.text
        assert "audio_queue_depth 0\n" in metrics.text
        expected_pending = next(
            int(line.split()[-1])
            for line in metrics.text.splitlines()
            if line.startswith("outbox_pending_events ")
        )
        assert expected_pending >= 3

    logs = capsys.readouterr().err
    assert _PRIVATE not in logs
    assert final["payload"]["text"] not in logs
    for event in (final, recommendation):
        matching = [
            entry
            for line in logs.splitlines()
            if line.startswith("{")
            if (entry := json.loads(line)).get("event_id") == event["event_id"]
        ]
        assert len(matching) == 1
        logged = matching[0]
        assert logged["event"] == event["event_type"]
        assert logged["session_id"] == logged["correlation_id"] == session_id
        assert logged["utterance_id"] == final["payload"]["utterance_id"]
        assert logged["duration_seconds"] >= 0
    if timeout:
        assert '"error_category": "timeout"' in logs


def test_disconnect_cancels_inflight_analysis_and_clears_gauges(
    database_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started = Event()
    cancelled = Event()

    class CompleteOnFrame(FakeSpeechRecognizer):
        async def accept_frame(self, frame: bytes) -> FinalizedUtterance:
            return FinalizedUtterance(
                utterance_id=uuid4(), text=_PRIVATE, start_ms=0, end_ms=100
            )

    async def complete(self: LlamaCpp, instructions: str, data: str) -> str:
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        raise AssertionError("Analysis should be cancelled on disconnect.")

    monkeypatch.setenv("LLM_ENABLED", "true")
    monkeypatch.setattr(LlamaCpp, "complete", complete)
    monkeypatch.setattr("bootstrap.main.FakeSpeechRecognizer", CompleteOnFrame)
    with TestClient(create_app()) as client:
        session_id = client.post("/api/sessions").json()["session_id"]
        with client.websocket_connect(f"/ws/sessions/{session_id}") as socket:
            socket.send_json(
                {
                    "schema_version": 1,
                    "session_id": session_id,
                    "event_type": "capture.start",
                }
            )
            assert socket.receive_json()["payload"]["status"] == "live"
            socket.send_bytes(b"\x01\x00" * 1600)
            assert socket.receive_json()["event_type"] == "transcript.final"
            assert started.wait(2)
        assert cancelled.is_set()
        metrics = client.get("/metrics").text
        assert "ws_disconnects_total 1\n" in metrics
        assert "live_sessions 0\n" in metrics
        assert "audio_buffer_seconds 0\n" in metrics
        assert (
            client.get(f"/api/sessions/{session_id}").json()["status"] == "interrupted"
        )
