"""Endpoints de liveness/readiness pour le microservice et pour prestd en amont."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from prestd_client import PrestdClient, PrestdError

from ..dependencies import get_client

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict:
    """Liveness de ce microservice uniquement — n'appelle pas prestd."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(client: PrestdClient = Depends(get_client)) -> dict:
    """Readiness : vérifie aussi que le prestd en amont répond."""
    try:
        upstream = await client.health()
        return {"status": "ok", "prestd": upstream}
    except PrestdError as exc:
        return {"status": "degraded", "prestd_error": str(exc)}
