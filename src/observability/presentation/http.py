import asyncio
from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Response

from observability.application.ports.metrics import MetricsView
from observability.application.use_cases.check_readiness import (
    CheckReadiness,
    DependencyStatus,
)


def routes(
    readiness: CheckReadiness,
    metrics: MetricsView,
    pending_count: Callable[[], Awaitable[int]],
    worker_counts: Callable[[], Awaitable[dict[str, int]]],
) -> APIRouter:
    router = APIRouter()

    @router.get("/readyz")
    async def readyz(
        response: Response,
    ) -> dict[str, str | dict[str, DependencyStatus]]:
        dependencies = await readiness.execute()
        ready = "unavailable" not in dependencies.values()
        response.status_code = 200 if ready else 503
        return {
            "status": "ready" if ready else "unavailable",
            "dependencies": dependencies,
        }

    async def read_pending() -> int | None:
        try:
            async with asyncio.timeout(2):
                return await pending_count()
        except Exception:
            return None

    @router.get("/metrics")
    async def scrape() -> Response:
        pending, worker = await asyncio.gather(read_pending(), worker_counts())
        return Response(
            metrics.render(pending, worker), media_type="text/plain; version=0.0.4"
        )

    return router
