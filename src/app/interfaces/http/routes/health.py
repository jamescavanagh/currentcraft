"""Liveness and readiness routes."""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from fastapi import APIRouter, Request, Response, status

from ..container import Container
from ..schemas import HealthResponse, ReadinessResponse

router = APIRouter(tags=["health"])


async def _run_bounded_check(
    check: Callable[[], Awaitable[bool]], timeout: float
) -> bool:
    try:
        return bool(await asyncio.wait_for(check(), timeout=timeout))
    except Exception:
        return False


@router.get(
    "/healthz",
    response_model=HealthResponse,
)
async def healthz() -> HealthResponse:
    """Return process liveness without querying any dependency."""
    return HealthResponse(status="ok")


@router.get(
    "/readyz",
    response_model=ReadinessResponse,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ReadinessResponse,
            "description": "One or more dependencies are not ready.",
        }
    },
)
async def readyz(request: Request, response: Response) -> ReadinessResponse:
    """Evaluate database and broker readiness callbacks with bounded timeouts."""
    container: Container = request.app.state.container
    timeout = container.settings.dependency_timeout_seconds

    pg_ok, nats_ok = await asyncio.gather(
        _run_bounded_check(container.database_ready, timeout),
        _run_bounded_check(container.broker_ready, timeout),
    )

    if pg_ok and nats_ok:
        return ReadinessResponse(status="ready", postgres=True, nats=True)

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="not_ready", postgres=pg_ok, nats=nats_ok)
