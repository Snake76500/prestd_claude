"""Dépendances FastAPI pour injecter facilement PrestdClient dans une application."""
from __future__ import annotations

from typing import Any, Callable

from .client import PrestdClient


def get_prestd_client_dependency(
    base_url: str | None = None,
    *,
    default_database: str | None = None,
    default_schema: str = "public",
    **default_kwargs: Any,
) -> Callable[..., PrestdClient]:
    """Factory de dépendance FastAPI.

    Transfère automatiquement le header `Authorization: Bearer <token>`
    de la requête entrante vers le client prestd s'il est présent.

    Exemple :
    ```python
    from fastapi import Depends, FastAPI
    from prestd_connector import PrestdClient, get_prestd_client_dependency

    app = FastAPI()
    get_client = get_prestd_client_dependency()

    @app.get("/users")
    async def list_users(client: PrestdClient = Depends(get_client)):
        return await client.table("users").execute()
    ```
    """
    async def _dependency(request: Any = None) -> PrestdClient:
        token = None
        if request is not None and hasattr(request, "headers"):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()

        return PrestdClient(
            base_url=base_url,
            default_database=default_database,
            default_schema=default_schema,
            token=token,
            **default_kwargs,
        )

    return _dependency
