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
    "action": "Сравните идентификаторы событий двух одинаковых уведомлений.",
    "rationale": "Совпадение идентификаторов указывает на повторную доставку.",
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
        ("grounded", ("duplicate-notifications",), "Совпадение идентификаторов", 2),
        ("unknown_id", (), "Локальная модель не смогла завершить анализ", 2),
        ("english_output", (), "Локальная модель не смогла завершить анализ", 2),
        ("ambiguous", (), "причину пока установить не удалось", 1),
        ("invalid_json", (), "Локальная модель не смогла завершить анализ", 1),
        ("timeout", (), "Локальная модель не смогла завершить анализ", 1),
        ("unavailable", (), "Локальная модель не смогла завершить анализ", 1),
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
            if case == "english_output":
                suggestion = {**suggestion, "action": "Compare event IDs."}
            assert "in Russian" in payload["messages"][0]["content"]
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


@pytest.mark.parametrize(
    ("latest", "faq_id", "action"),
    [
        (
            "Вебхук не успевает ответить до тайм-аута.",
            "webhook-timeout",
            "Сравните время ответа вебхука с тайм-аутом отправителя.",
        ),
        (
            "У двух доставок одинаковый идентификатор.",
            "idempotency",
            "Сохраняйте стабильный идентификатор события",
        ),
        (
            "Отправитель повторно отправляет событие после ошибки 503.",
            "event-retries",
            "Проверьте число попыток доставки",
        ),
        (
            "События приходят не по порядку.",
            "event-order",
            "Сравните порядковые номера событий",
        ),
    ],
)
def test_latest_detail_takes_priority_over_original_issue(
    latest: str, faq_id: str, action: str
) -> None:
    previous = SUGGESTION["action"]
    assert isinstance(previous, str)
    transcript = f"Клиенты получают дубликаты уведомлений дважды.\n{latest}"

    class Model:
        async def complete(self, instructions: str, data: str) -> str:
            payload = json.loads(data)
            if "transcript" in payload:
                assert payload["transcript"] == transcript
                return json.dumps(CONTEXT)
            raise AssertionError(
                "A uniquely matched follow-up uses the FAQ recommendation."
            )

    analysis = SupportAnalysis(Model(), FAQ().search)
    result = asyncio.run(
        analysis.analyze(
            uuid4(), 2, transcript, latest_text=latest, previous_action=previous
        )
    )
    assert result.recommendation.action.startswith(action)
    assert result.recommendation.faq_ids == (faq_id,)
