import asyncio
import os
from time import perf_counter
from uuid import uuid4

import httpx

from agents.application.analysis import SupportAnalysis
from agents.infrastructure.llama_cpp import LlamaCpp
from knowledge.faq import FAQ


async def main() -> None:
    async with httpx.AsyncClient(trust_env=False) as client:
        model = LlamaCpp(
            client,
            os.getenv("LLM_ENDPOINT", "http://127.0.0.1:8080/v1"),
            os.getenv("LLM_MODEL", "Forge-1-E2B-Q4_K_M.gguf"),
        )
        start = perf_counter()
        analysis = SupportAnalysis(model, FAQ().search)
        transcript = ""
        previous_action = None
        for version, (phrase, expected) in enumerate(
            (
                (
                    "Клиенты получают дубликаты уведомлений от API.",
                    "duplicate-notifications",
                ),
                ("У двух доставок одинаковый идентификатор.", "idempotency"),
                ("Вебхук не успевает ответить до тайм-аута.", "webhook-timeout"),
            ),
            start=1,
        ):
            transcript = f"{transcript}\n{phrase}".strip()
            result = await analysis.analyze(
                uuid4(),
                version,
                transcript,
                latest_text=phrase,
                previous_action=previous_action,
            )
            recommendation = result.recommendation
            print(f"{perf_counter() - start:.2f}s {recommendation.model_dump_json()}")
            if (
                expected not in recommendation.faq_ids
                or previous_action == recommendation.action
            ):
                raise SystemExit(f"Expected a new action citing {expected}.")
            previous_action = recommendation.action


if __name__ == "__main__":
    asyncio.run(main())
