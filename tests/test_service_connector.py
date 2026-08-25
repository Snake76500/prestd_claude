"""Tests unitaires pour PrestdServiceConnector et la dépendance FastAPI get_service_connector."""
from __future__ import annotations

import pytest
import respx
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from httpx import Response

from prestd_client import (
    PaginatedResponse,
    PrestdServiceConnector,
    SyncPrestdServiceConnector,
    get_service_connector,
)


@pytest.mark.asyncio
@respx.mock
async def test_connector_health_and_meta():
    """Vérifie les appels aux endpoints de santé et de métadonnées du microservice."""
    respx.get("http://microservice:8000/healthz").mock(return_value=Response(200, json={"status": "healthy"}))
    respx.get("http://microservice:8000/readyz").mock(return_value=Response(200, json={"status": "ready"}))
    respx.get("http://microservice:8000/meta/databases").mock(return_value=Response(200, json=[{"datname": "prest"}]))
    respx.get("http://microservice:8000/meta/schemas").mock(return_value=Response(200, json=[{"schema_name": "public"}]))
    respx.get("http://microservice:8000/meta/tables").mock(return_value=Response(200, json=[{"table_name": "users"}]))

    async with PrestdServiceConnector("http://microservice:8000") as connector:
        assert await connector.health() == {"status": "healthy"}
        assert await connector.ready() == {"status": "ready"}
        assert await connector.databases() == [{"datname": "prest"}]
        assert await connector.schemas() == [{"schema_name": "public"}]
        assert await connector.tables() == [{"table_name": "users"}]


@pytest.mark.asyncio
@respx.mock
async def test_connector_paginated_list():
    """Vérifie la récupération paginée via l'API fluide table().filter().page().list()."""
    mock_envelope = {
        "data": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
        "page": 1,
        "page_size": 10,
        "total_rows": 25,
        "total_pages": 3,
    }
    route = respx.get("http://microservice:8000/tables/users").mock(
        return_value=Response(200, json=mock_envelope)
    )

    async with PrestdServiceConnector("http://microservice:8000", api_key="secret-api-key") as connector:
        res: PaginatedResponse = (
            await connector.table("users")
            .filter(role="$eq.admin", active="true")
            .select("id", "name")
            .order_by("-created_at")
            .page(1, 10)
            .list()
        )

        assert res.data == [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]
        assert res.page == 1
        assert res.page_size == 10
        assert res.total_rows == 25
        assert res.total_pages == 3

        # Vérification des headers & query params envoyés
        sent_request = route.calls.last.request
        assert sent_request.headers["X-API-Key"] == "secret-api-key"
        assert sent_request.url.params["role"] == "$eq.admin"
        assert sent_request.url.params["active"] == "true"
        assert sent_request.url.params["_select"] == "id,name"
        assert sent_request.url.params["_order"] == "-created_at"
        assert sent_request.url.params["_page"] == "1"
        assert sent_request.url.params["_page_size"] == "10"


@pytest.mark.asyncio
@respx.mock
async def test_connector_crud_operations():
    """Vérifie les opérations CRUD d'insertion, mise à jour et suppression."""
    respx.post("http://microservice:8000/tables/users").mock(
        return_value=Response(201, json={"id": 3, "name": "Charlie"})
    )
    respx.patch("http://microservice:8000/tables/users").mock(
        return_value=Response(200, json={"id": 3, "name": "Charlie Updated"})
    )
    respx.delete("http://microservice:8000/tables/users").mock(
        return_value=Response(200, json={"deleted": 1})
    )

    async with PrestdServiceConnector("http://microservice:8000", token="jwt-token") as connector:
        # Create
        created = await connector.table("users").create({"name": "Charlie"})
        assert created == {"id": 3, "name": "Charlie"}

        # Update
        updated = await connector.table("users").update({"name": "Charlie Updated"}, filters={"id": "3"})
        assert updated == {"id": 3, "name": "Charlie Updated"}

        # Delete
        deleted = await connector.table("users").delete(filters={"id": "3"})
        assert deleted == {"deleted": 1}


@pytest.mark.asyncio
@respx.mock
async def test_connector_scoped_datasource_schema():
    """Vérifie les appels ciblant un datasource et un schéma explicites."""
    respx.get("http://microservice:8000/datasource/mydb/schema/analytics/table/reports").mock(
        return_value=Response(200, json={"data": [{"id": 10, "metric": 99.5}], "total_rows": 1, "page": 1, "page_size": 10, "total_pages": 1})
    )

    async with PrestdServiceConnector("http://microservice:8000") as connector:
        res = await connector.datasource("mydb").schema("analytics").table("reports").list()
        assert res.data == [{"id": 10, "metric": 99.5}]


def test_sync_prestd_service_connector():
    """Vérifie le fonctionnement du connecteur synchrone."""
    with respx.mock:
        respx.get("http://microservice:8000/tables/users").mock(
            return_value=Response(200, json={"data": [{"id": 1}], "page": 1, "page_size": 10, "total_rows": 1, "total_pages": 1})
        )

        with SyncPrestdServiceConnector("http://microservice:8000") as client:
            res = client.list_rows("users")
            assert res.data == [{"id": 1}]


def test_fastapi_dependency_injection():
    """Vérifie l'injection de get_service_connector() dans une application FastAPI cliente."""
    app = FastAPI()

    @app.get("/proxy-users")
    async def get_users(connector: PrestdServiceConnector = Depends(get_service_connector(base_url="http://microservice:8000"))):
        res = await connector.table("users").page(1, 5).list()
        return {"items": res.data, "total": res.total_rows}

    with respx.mock:
        respx.get("http://microservice:8000/tables/users").mock(
            return_value=Response(200, json={"data": [{"id": 1, "name": "Alice"}], "page": 1, "page_size": 5, "total_rows": 1, "total_pages": 1})
        )

        client = TestClient(app)
        response = client.get("/proxy-users", headers={"Authorization": "Bearer keycloak-user-token"})
        assert response.status_code == 200
        assert response.json() == {"items": [{"id": 1, "name": "Alice"}], "total": 1}


@pytest.mark.asyncio
@respx.mock
async def test_connector_streaming():
    """Vérifie le streaming de pages via le connecteur."""
    respx.get("http://microservice:8000/tables/users", params={"_page": "1", "_page_size": "2"}).mock(
        return_value=Response(200, json={"data": [{"id": 1}, {"id": 2}], "page": 1, "page_size": 2, "total_rows": 3, "total_pages": 2})
    )
    respx.get("http://microservice:8000/tables/users", params={"_page": "2", "_page_size": "2"}).mock(
        return_value=Response(200, json={"data": [{"id": 3}], "page": 2, "page_size": 2, "total_rows": 3, "total_pages": 2})
    )

    async with PrestdServiceConnector("http://microservice:8000") as connector:
        items = []
        async for row in connector.table("users").stream(batch_size=2):
            items.append(row["id"])

        assert items == [1, 2, 3]
