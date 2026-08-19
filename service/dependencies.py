"""Dépendances FastAPI partagées : instance du client prestd, auth par API key."""
from __future__ import annotations

from fastapi import Header, HTTPException, Request, status

from prestd_client import PrestdClient

from .config import settings


def get_client(request: Request) -> PrestdClient:
    """Récupère le PrestdClient partagé, créé une fois au démarrage (voir main.py)."""
    return request.app.state.prestd_client


async def require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    """Protège les routes avec `X-API-Key`. Désactivé si SERVICE_API_KEY n'est pas défini ou vide."""
    if not settings.service_api_key:
        return
    if x_api_key != settings.service_api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key manquante ou invalide"
        )


def get_current_user(request: Request):
    """Récupère le UserContext injecté par le middleware KeycloakPermissionMiddleware."""
    return getattr(request.state, "user", None)

