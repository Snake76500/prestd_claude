"""Connecteur Python et dépendance FastAPI pour le microservice prestd / Swagger.

Ce module permet de consommer les endpoints exposés par le microservice FastAPI :
- Santé & Disponibilité (/healthz, /readyz)
- Métadonnées (/meta/databases, /meta/schemas, /meta/tables)
- Données paginées & filtrées (/tables/{table} et /datasource/.../table/{table})
- Insertion, mise à jour et suppression avec support X-API-Key et Token Keycloak.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator, Mapping, Sequence

import httpx

from .exceptions import PrestdConnectionError, raise_for_status


@dataclass
class PaginatedResponse:
    """Représentation typée de l'enveloppe de réponse retournée par les endpoints GET du microservice."""

    data: list[dict[str, Any]]
    page: int = 1
    page_size: int = 10
    total_rows: int = 0
    total_pages: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, Any] | list[Any]) -> "PaginatedResponse":
        if isinstance(data, dict) and "data" in data:
            return cls(
                data=data.get("data") or [],
                page=int(data.get("page", 1)),
                page_size=int(data.get("page_size", len(data.get("data") or []))),
                total_rows=int(data.get("total_rows", len(data.get("data") or []))),
                total_pages=int(data.get("total_pages", 1)),
            )
        elif isinstance(data, list):
            return cls(
                data=data,
                page=1,
                page_size=len(data),
                total_rows=len(data),
                total_pages=1,
            )
        return cls(data=[])


class ServiceTableConnector:
    """Interface fluide pour interagir avec une table du microservice Swagger (SELECT, INSERT, UPDATE, DELETE)."""

    def __init__(
        self,
        connector: "PrestdServiceConnector",
        table: str,
        *,
        datasource: str | None = None,
        schema: str | None = None,
    ) -> None:
        self._connector = connector
        self._table = table
        self._datasource = datasource
        self._schema = schema
        self._filters: dict[str, Any] = {}
        self._select_cols: str | None = None
        self._order_by: str | None = None
        self._page: int | None = None
        self._page_size: int | None = None
        self._distinct: bool | None = None
        self._groupby: str | None = None
        self._count: str | None = None
        self._or_condition: str | None = None

    def filter(self, *filter_strings: str, **kwargs: Any) -> "ServiceTableConnector":
        """Ajoute des filtres de colonnes (ex: `user="$eq.TOTO"`, `status="active"` ou `"age=$gte.18"`)."""
        for fs in filter_strings:
            if "=" in fs:
                k, v = fs.split("=", 1)
                self._filters[k.strip()] = v.strip()
            else:
                self._filters[fs.strip()] = ""
        for k, v in kwargs.items():
            self._filters[k] = v
        return self

    def select(self, *columns: str) -> "ServiceTableConnector":
        """Sélectionne des colonnes spécifiques (ex: `.select("id", "name", "email")`)."""
        self._select_cols = ",".join(columns)
        return self

    def order_by(self, *columns: str) -> "ServiceTableConnector":
        """Définit le tri (ex: `.order_by("-created_at", "name")`)."""
        self._order_by = ",".join(columns)
        return self

    def page(self, page: int = 1, page_size: int = 10) -> "ServiceTableConnector":
        """Configure la pagination (1-indexé)."""
        self._page = page
        self._page_size = page_size
        return self

    def distinct(self, enable: bool = True) -> "ServiceTableConnector":
        """Active la déduplication SELECT DISTINCT."""
        self._distinct = enable
        return self

    def group_by(self, *columns: str) -> "ServiceTableConnector":
        """Groupe par colonne(s)."""
        self._groupby = ",".join(columns)
        return self

    def count(self, column: str = "*") -> "ServiceTableConnector":
        """Compte les enregistrements (ex: `.count("*")`)."""
        self._count = column
        return self

    def or_conditions(self, expression: str) -> "ServiceTableConnector":
        """Spécifie des conditions OU logiques (ex: `'name=$ilike.%a%||email=$ilike.%a%'`)."""
        self._or_condition = expression
        return self

    async def list(self) -> PaginatedResponse:
        """GET /tables/{table} — Récupère les enregistrements selon les filtres et pagination configurés."""
        return await self._connector.list_rows(
            table=self._table,
            datasource=self._datasource,
            schema=self._schema,
            filters=self._filters,
            select=self._select_cols,
            order=self._order_by,
            page=self._page,
            page_size=self._page_size,
            distinct=self._distinct,
            groupby=self._groupby,
            count=self._count,
            or_conditions=self._or_condition,
        )

    async def stream_pages(self, batch_size: int = 10) -> AsyncIterator[list[dict[str, Any]]]:
        """Générateur asynchrone itérant page par page via le microservice."""
        current_page = 1
        while True:
            res = await self._connector.list_rows(
                table=self._table,
                datasource=self._datasource,
                schema=self._schema,
                filters=self._filters,
                select=self._select_cols,
                order=self._order_by,
                page=current_page,
                page_size=batch_size,
                distinct=self._distinct,
                groupby=self._groupby,
                count=self._count,
                or_conditions=self._or_condition,
            )
            if not res.data:
                break
            yield res.data
            if len(res.data) < batch_size or (res.total_pages and current_page >= res.total_pages):
                break
            current_page += 1

    async def stream(self, batch_size: int = 10) -> AsyncIterator[dict[str, Any]]:
        """Générateur asynchrone itérant enregistrement par enregistrement à travers toutes les pages."""
        async for page_rows in self.stream_pages(batch_size=batch_size):
            for row in page_rows:
                yield row

    async def first(self) -> dict[str, Any] | None:
        """Récupère le premier enregistrement correspondant ou None."""
        self.page(page=1, page_size=1)
        res = await self.list()
        return res.data[0] if res.data else None

    async def create(self, data: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Any:
        """POST /tables/{table} — Insère une ligne unique (objet JSON) ou un lot (liste d'objets)."""
        return await self._connector.create_row(
            table=self._table,
            data=data,
            datasource=self._datasource,
            schema=self._schema,
        )

    async def update(
        self,
        data: Mapping[str, Any],
        filters: Mapping[str, Any] | None = None,
    ) -> Any:
        """PATCH /tables/{table} — Met à jour les enregistrements ciblés par les filtres."""
        combined_filters = dict(self._filters)
        if filters:
            combined_filters.update(filters)
        return await self._connector.update_rows(
            table=self._table,
            data=data,
            filters=combined_filters,
            datasource=self._datasource,
            schema=self._schema,
        )

    async def delete(self, filters: Mapping[str, Any] | None = None) -> Any:
        """DELETE /tables/{table} — Supprime les enregistrements ciblés par les filtres."""
        combined_filters = dict(self._filters)
        if filters:
            combined_filters.update(filters)
        return await self._connector.delete_rows(
            table=self._table,
            filters=combined_filters,
            datasource=self._datasource,
            schema=self._schema,
        )


class PrestdServiceConnector:
    """Connecteur HTTP Asynchrone pour le microservice FastAPI Swagger."""

    def __init__(
        self,
        base_url: str = "http://localhost:8000",
        *,
        api_key: str | None = None,
        token: str | None = None,
        timeout: float = 30.0,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.token = token
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            verify=verify,
            transport=transport,
        )

    async def __aenter__(self) -> "PrestdServiceConnector":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    def set_token(self, token: str) -> None:
        """Définit le token JWT Bearer (Keycloak)."""
        self.token = token

    def set_api_key(self, api_key: str) -> None:
        """Définit la clé API X-API-Key."""
        self.api_key = api_key

    # -- Endpoints Santé & Métadonnées ----------------------------------------
    async def health(self) -> dict[str, Any]:
        """GET /healthz — Santé basique."""
        return await self._request("GET", "/healthz")

    async def ready(self) -> dict[str, Any]:
        """GET /readyz — Vérifie la connexion effective à prestd."""
        return await self._request("GET", "/readyz")

    async def databases(self) -> list[dict[str, Any]]:
        """GET /meta/databases — Liste les bases de données."""
        return await self._request("GET", "/meta/databases")

    async def schemas(self) -> list[dict[str, Any]]:
        """GET /meta/schemas — Liste les schémas."""
        return await self._request("GET", "/meta/schemas")

    async def tables(self) -> list[dict[str, Any]]:
        """GET /meta/tables — Liste les tables."""
        return await self._request("GET", "/meta/tables")

    # -- Interface Table fluide -----------------------------------------------
    def table(
        self,
        table_name: str,
        *,
        datasource: str | None = None,
        schema: str | None = None,
    ) -> ServiceTableConnector:
        """Retourne une interface fluide pour requêter une table."""
        return ServiceTableConnector(self, table_name, datasource=datasource, schema=schema)

    def datasource(self, datasource_name: str, schema: str | None = None) -> "_DatasourceScope":
        """Définit une portée de datasource pour requêter des tables."""
        return _DatasourceScope(self, datasource_name, schema)

    # -- Endpoints Records directs --------------------------------------------
    def _build_path(
        self,
        table: str,
        datasource: str | None = None,
        schema: str | None = None,
    ) -> str:
        if datasource and schema:
            return f"/datasource/{datasource}/schema/{schema}/table/{table}"
        elif datasource:
            return f"/datasource/{datasource}/{table}"
        return f"/tables/{table}"

    async def list_rows(
        self,
        table: str,
        *,
        datasource: str | None = None,
        schema: str | None = None,
        filters: Mapping[str, Any] | None = None,
        select: str | None = None,
        order: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        distinct: bool | None = None,
        groupby: str | None = None,
        count: str | None = None,
        or_conditions: str | None = None,
    ) -> PaginatedResponse:
        """GET /tables/{table} ou /datasource/... — Liste et filtre les enregistrements."""
        path = self._build_path(table, datasource=datasource, schema=schema)
        params: dict[str, Any] = {}
        if filters:
            for k, v in filters.items():
                params[k] = v
        if select:
            params["_select"] = select
        if order:
            params["_order"] = order
        if page is not None:
            params["_page"] = page
        if page_size is not None:
            params["_page_size"] = page_size
        if distinct is not None:
            params["_distinct"] = str(distinct).lower()
        if groupby:
            params["_groupby"] = groupby
        if count:
            params["_count"] = count
        if or_conditions:
            params["_or"] = or_conditions

        resp = await self._request("GET", path, params=params)
        return PaginatedResponse.from_dict(resp)

    async def create_row(
        self,
        table: str,
        data: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        datasource: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """POST /tables/{table} ou /datasource/... — Insertion (ligne ou lot)."""
        path = self._build_path(table, datasource=datasource, schema=schema)
        payload = list(data) if isinstance(data, (list, tuple)) else dict(data)
        return await self._request("POST", path, json=payload)

    async def update_rows(
        self,
        table: str,
        data: Mapping[str, Any],
        filters: Mapping[str, Any],
        *,
        datasource: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """PATCH /tables/{table} ou /datasource/... — Mise à jour filtrée."""
        if not filters:
            raise ValueError("Au moins un filtre est requis pour une mise à jour.")
        path = self._build_path(table, datasource=datasource, schema=schema)
        return await self._request("PATCH", path, params=dict(filters), json=dict(data))

    async def delete_rows(
        self,
        table: str,
        filters: Mapping[str, Any],
        *,
        datasource: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """DELETE /tables/{table} ou /datasource/... — Suppression filtrée."""
        if not filters:
            raise ValueError("Au moins un filtre est requis pour une suppression.")
        path = self._build_path(table, datasource=datasource, schema=schema)
        return await self._request("DELETE", path, params=dict(filters))

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        if self.token:
            headers.setdefault("Authorization", f"Bearer {self.token}")
        if self.api_key:
            headers.setdefault("X-API-Key", self.api_key)

        try:
            resp = await self._http.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException as exc:
            raise PrestdConnectionError(f"Timeout sur le microservice {method} {path}") from exc
        except httpx.TransportError as exc:
            raise PrestdConnectionError(
                f"Impossible de joindre le microservice à {self.base_url}{path}: {exc}"
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


class _DatasourceScope:
    def __init__(self, connector: PrestdServiceConnector, datasource: str, schema: str | None = None) -> None:
        self._connector = connector
        self._datasource = datasource
        self._schema = schema

    def schema(self, schema_name: str) -> "_DatasourceScope":
        self._schema = schema_name
        return self

    def table(self, table_name: str) -> ServiceTableConnector:
        return ServiceTableConnector(
            self._connector,
            table_name,
            datasource=self._datasource,
            schema=self._schema,
        )


class SyncPrestdServiceConnector:
    """Connecteur HTTP Synchrone pour scripts et notebooks."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._async = PrestdServiceConnector(*args, **kwargs)

    def _run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def __enter__(self) -> "SyncPrestdServiceConnector":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        self._run(self._async.close())

    def set_token(self, token: str) -> None:
        self._async.set_token(token)

    def set_api_key(self, api_key: str) -> None:
        self._async.set_api_key(api_key)

    def health(self) -> dict[str, Any]:
        return self._run(self._async.health())

    def ready(self) -> dict[str, Any]:
        return self._run(self._async.ready())

    def databases(self) -> list[dict[str, Any]]:
        return self._run(self._async.databases())

    def schemas(self) -> list[dict[str, Any]]:
        return self._run(self._async.schemas())

    def tables(self) -> list[dict[str, Any]]:
        return self._run(self._async.tables())

    def list_rows(self, table: str, **kwargs: Any) -> PaginatedResponse:
        return self._run(self._async.list_rows(table, **kwargs))

    def create_row(self, table: str, data: Any, **kwargs: Any) -> Any:
        return self._run(self._async.create_row(table, data, **kwargs))

    def update_rows(self, table: str, data: Any, filters: Any, **kwargs: Any) -> Any:
        return self._run(self._async.update_rows(table, data, filters, **kwargs))

    def delete_rows(self, table: str, filters: Any, **kwargs: Any) -> Any:
        return self._run(self._async.delete_rows(table, filters, **kwargs))


# -- Dépendance FastAPI pour applications clientes ----------------------------
def get_service_connector(
    base_url: str | None = None,
    api_key: str | None = None,
) -> Any:
    """Factory de dépendance FastAPI pour injecter un PrestdServiceConnector prêt à l'emploi.

    Exemple d'utilisation dans une application FastAPI cliente :
    ```python
    from fastapi import Depends, FastAPI
    from prestd_client import PrestdServiceConnector, get_service_connector

    app = FastAPI()

    @app.get("/my-users")
    async def get_my_users(connector: PrestdServiceConnector = Depends(get_service_connector())):
        res = await connector.table("users").page(1, 10).list()
        return res.data
    ```
    """
    default_url = base_url or os.getenv("PRESTD_SERVICE_URL", "http://localhost:8000")
    default_api_key = api_key or os.getenv("PRESTD_SERVICE_API_KEY", None)

    async def _dependency(request: Any = None) -> PrestdServiceConnector:
        # Récupération automatique du token Authorization si présent dans la requête parente
        token = None
        req_api_key = default_api_key
        if request is not None and hasattr(request, "headers"):
            auth_header = request.headers.get("Authorization", "")
            if auth_header.lower().startswith("bearer "):
                token = auth_header[7:].strip()
            if "x-api-key" in request.headers:
                req_api_key = request.headers.get("x-api-key")

        return PrestdServiceConnector(
            base_url=default_url,
            api_key=req_api_key,
            token=token,
        )

    return _dependency
