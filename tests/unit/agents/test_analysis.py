import asyncio
import json
from uuid import uuid4

import httpx
import pytest

from agents.infrastructure.llama_cpp import LlamaCpp
from agents.public import SupportAnalysis
from knowledge.faq import FAQ

CONTEXT = {
    "status": "identified",
    "issue": "Duplicate API notifications",
    "intent": "Diagnose duplicate deliveries",
    "confidence": 0.9,
}
SUGGESTION = {
    "action": "Compare the event IDs of two duplicate notifications.",
    "rationale": "Matching IDs indicate repeat delivery of the same event.",
    "faq_ids": ["duplicate-notifications"],
}


def test_faq_lookup_is_deterministic() -> None:
    faq = FAQ()
    assert not faq.search("The weather looks sunny.")
    assert list(faq.search("duplicate notifications and retries")) == [
        "duplicate-notifications",
        "event-retries",
    ]
    assert list(faq.search("Уведомления приходят дважды")) == [
        "duplicate-notifications"
    ]


@pytest.mark.parametrize(
    ("case", "expected_citations", "expected_rationale", "expected_calls"),
    [
        ("grounded", ("duplicate-notifications",), "Matching IDs", 2),
        ("unknown_id", (), "Local AI analysis could not finish", 2),
        ("ambiguous", (), "The cause is unconfirmed", 1),
        ("invalid_json", (), "Local AI analysis could not finish", 1),
        ("timeout", (), "Local AI analysis could not finish", 1),
        ("unavailable", (), "Local AI analysis could not finish", 1),
    ],
)
def test_analysis_with_fake_endpoint(
    case: str,
    expected_citations: tuple[str, ...],
    expected_rationale: str,
    expected_calls: int,
) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url == httpx.URL("http://127.0.0.1:8080/v1/chat/completions")
        payload = json.loads(request.content)
        assert payload["model"] == "local-model"
        assert payload["max_tokens"] == 320
        assert "tools" not in payload
        if case == "timeout":
            raise httpx.ReadTimeout("Timed out", request=request)
        if case == "unavailable":
            return httpx.Response(503)
        if len(requests) == 1:
            context = (
                {"status": "insufficient_context"} if case == "ambiguous" else CONTEXT
            )
            content = "{" if case == "invalid_json" else json.dumps(context)
        else:
            evidence = json.loads(payload["messages"][1]["content"])["faq"]
            assert "duplicate-notifications" in evidence
            suggestion = (
                {**SUGGESTION, "faq_ids": ["invented"]}
                if case == "unknown_id"
                else SUGGESTION
            )
            content = json.dumps(suggestion)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": content}}]}
        )

    async def run() -> None:
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(respond), trust_env=False
        ) as client:
            analysis = SupportAnalysis(
                LlamaCpp(client, "http://127.0.0.1:8080/v1", "local-model"),
                FAQ().search,
            )
            utterance_id = uuid4()
            result = await analysis.analyze(
                utterance_id,
                2,
                "It happened again."
                if case == "ambiguous"
                else "We get duplicate API notifications.",
            )
            assert result.recommendation.utterance_id == utterance_id
            assert result.recommendation.context_version == 2
            assert result.recommendation.faq_ids == expected_citations
            assert expected_rationale in result.recommendation.rationale
            if case == "grounded":
                assert result.context is not None
                assert result.context.model_dump() == CONTEXT
                assert result.recommendation.action == SUGGESTION["action"]

    asyncio.run(run())
    assert len(requests) == expected_calls


def test_remote_endpoint_is_rejected() -> None:
    async def run() -> None:
        async with httpx.AsyncClient() as client:
            with pytest.raises(ValueError, match="loopback"):
                LlamaCpp(client, "http://127.0.0.1.example.org/v1", "local-model")

    asyncio.run(run())
