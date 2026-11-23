import asyncio
from typing import Literal

from observability.application.ports.readiness import Probe

type DependencyStatus = Literal["ready", "unavailable", "disabled"]


class CheckReadiness:
    def __init__(self, probes: dict[str, Probe | None]) -> None:
        self._probes = probes

    async def execute(self) -> dict[str, DependencyStatus]:
        async def check(probe: Probe | None) -> DependencyStatus:
            if probe is None:
                return "disabled"
            try:
                async with asyncio.timeout(2):
                    return "ready" if await probe() else "unavailable"
            except Exception:
                return "unavailable"

        statuses = await asyncio.gather(
            *(check(probe) for probe in self._probes.values())
        )
        return dict(zip(self._probes, statuses, strict=True))
