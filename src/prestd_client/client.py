"""Client HTTP asynchrone pour prestd (https://docs.prestd.com).

Couvre les endpoints documentés dans l'API Reference officielle :
- GET  /_health, /_ready
- GET  /databases, /schemas, /tables, /show/{db}/{schema}/{table}
- GET  /{db}/{schema}/{table}      (SELECT, filtres, pagination, tri...)
- POST /{db}/{schema}/{table}      (INSERT, y compris en lot)
- PATCH|PUT /{db}/{schema}/{table} (UPDATE filtré par query string)
- DELETE    /{db}/{schema}/{table} (DELETE filtré par query string)
- POST /auth                       (login JWT, si PREST_AUTH_ENABLED=true)
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

import httpx

from .exceptions import PrestdAuthError, PrestdConnectionError, raise_for_status
from .query import QueryBuilder

logger = logging.getLogger("prestd_client")

DEFAULT_TIMEOUT = 30.0


class PrestdClient:
    """Wrapper asynchrone léger autour d'un serveur prestd.

    Exemple
    -------
    ```python
    async with PrestdClient("http://localhost:3000", default_database="mydb") as client:
        await client.login("prest", "prest")  # si PREST_AUTH_ENABLED=true
        rows = await client.table("users").eq("active", True).order("-created_at").execute()
    ```
    """

    def __init__(
        self,
        base_url: str,
        *,
        default_database: str | None = None,
        default_schema: str = "public",
        timeout: float = DEFAULT_TIMEOUT,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_database = default_database
        self.default_schema = default_schema
        self._token: str | None = None
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            verify=verify,
            transport=transport,
        )

    # -- cycle de vie ----------------------------------------------------
    async def __aenter__(self) -> "PrestdClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    def set_token(self, token: str) -> None:
        """Attache manuellement un JWT déjà généré (évite un aller-retour /auth)."""
        self._token = token

    # -- authentification --------------------------------------------------
    async def login(self, username: str, password: str) -> str:
        """POST /auth — fonctionne uniquement si prestd tourne avec PREST_AUTH_ENABLED=true."""
        resp = await self._request(
            "POST", "/auth", json={"username": username, "password": password}
        )
        token = None
        if isinstance(resp, dict):
            token = resp.get("token") or resp.get("access_token")
        if not token:
            raise PrestdAuthError("La réponse de prestd /auth ne contient pas de token", payload=resp)
        self._token = token
        return token

    # -- découverte du schéma ---------------------------------------------
    async def health(self) -> Any:
        return await self._request("GET", "/_health")

    async def ready(self) -> Any:
        return await self._request("GET", "/_ready")

    async def databases(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/databases")

    async def schemas(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/schemas")

    async def tables(self) -> list[dict[str, Any]]:
        return await self._request("GET", "/tables")

    async def describe_table(
        self, table: str, *, database: str | None = None, schema: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /show/{database}/{schema}/{table} — structure de la table (colonnes, types...)."""
        db, sch = self._resolve(database, schema)
        return await self._request("GET", f"/show/{db}/{sch}/{table}")

    # -- CRUD ----------------------------------------------------------------
    def table(self, table: str, *, database: str | None = None, schema: str | None = None) -> QueryBuilder:
        """Point d'entrée fluide : `client.table("users").eq("active", True).execute()`."""
        db, sch = self._resolve(database, schema)
        return QueryBuilder(self, db, sch, table)

    async def insert(
        self,
        table: str,
        data: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """INSERT. `data` peut être un dict (une ligne) ou une liste de dicts (insertion en lot)."""
        db, sch = self._resolve(database, schema)
        return await self._request("POST", f"/{db}/{sch}/{table}", json=data)

    async def update(
        self,
        table: str,
        data: Mapping[str, Any],
        filters: Mapping[str, str],
        *,
        database: str | None = None,
        schema: str | None = None,
        method: str = "PATCH",
    ) -> Any:
        """UPDATE filtré. `filters` est un dict `{champ: valeur_ou_operateur}`.

        prestd exécute un UPDATE inconditionnel (toutes les lignes) si aucun
        filtre n'est fourni ; ce client refuse ce cas par sécurité.
        """
        if not filters:
            raise ValueError(
                "update() nécessite au moins un filtre — prestd exécute sinon un "
                "UPDATE inconditionnel sur toutes les lignes de la table."
            )
        db, sch = self._resolve(database, schema)
        return await self._request(method, f"/{db}/{sch}/{table}", params=dict(filters), json=data)

    async def delete(
        self,
        table: str,
        filters: Mapping[str, str],
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """DELETE filtré. Même garde-fou que `update()` : filtres obligatoires."""
        if not filters:
            raise ValueError(
                "delete() nécessite au moins un filtre — prestd exécute sinon un "
                "DELETE inconditionnel sur toutes les lignes de la table."
            )
        db, sch = self._resolve(database, schema)
        return await self._request("DELETE", f"/{db}/{sch}/{table}", params=dict(filters))

    async def batch_insert(
        self,
        table: str,
        records: Sequence[Mapping[str, Any]],
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """Sucre syntaxique : prestd accepte un tableau JSON sur le même endpoint POST."""
        return await self.insert(table, list(records), database=database, schema=schema)

    # -- interne ---------------------------------------------------------------
    async def _get_rows(
        self, database: str, schema: str, table: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        result = await self._request("GET", f"/{database}/{schema}/{table}", params=params)
        if isinstance(result, list):
            return result
        return [result] if result else []

    def _resolve(self, database: str | None, schema: str | None) -> tuple[str, str]:
        db = database or self.default_database
        if not db:
            raise ValueError(
                "Aucune database fournie et aucun default_database configuré sur PrestdClient."
            )
        sch = schema or self.default_schema
        return db, sch

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = kwargs.pop("headers", {}) or {}
        if self._token:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        try:
            resp = await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise PrestdConnectionError(f"Timeout en appelant prestd {method} {path}") from exc
        except httpx.TransportError as exc:
            raise PrestdConnectionError(
                f"Impossible de joindre prestd à {self.base_url}{path}: {exc}"
            ) from exc

        if resp.status_code >= 400:
            try:
                payload = resp.json()
                message = payload.get("error") or payload.get("message") or resp.text
            except Exception:
                payload, message = None, resp.text
            raise_for_status(resp.status_code, message, payload)

        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text
