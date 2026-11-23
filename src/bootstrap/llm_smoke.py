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
        result = await SupportAnalysis(model, FAQ().search).analyze(
            uuid4(), 1, "Customers are receiving duplicate API notifications."
        )
        print(
            f"{perf_counter() - start:.2f}s {result.recommendation.model_dump_json()}"
        )
        if "duplicate-notifications" not in result.recommendation.faq_ids:
            raise SystemExit("Expected the duplicate-notifications FAQ citation.")


if __name__ == "__main__":
    asyncio.run(main())
