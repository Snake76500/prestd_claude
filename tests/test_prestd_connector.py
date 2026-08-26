"""Tests unitaires pour le package prestd_connector."""
from __future__ import annotations

import os
import pytest
import respx
from httpx import Response
from prestd_client import JWTAuth, KeycloakAuth, StaticTokenAuth
from prestd_connector import PrestdClient, SyncPrestdClient, get_prestd_client_dependency


@pytest.mark.asyncio
async def test_connector_defaults(monkeypatch):
    """Vérifie la résolution des variables d'environnement par défaut."""
    monkeypatch.setenv("PRESTD_URL", "http://myprest:4000")
    monkeypatch.setenv("PRESTD_DATABASE", "production_db")
    monkeypatch.setenv("PRESTD_SCHEMA", "analytics")

    client = PrestdClient()
    assert client.base_url == "http://myprest:4000"
    assert client.default_database == "production_db"
    assert client.default_schema == "analytics"
    await client.close()


@pytest.mark.asyncio
async def test_connector_static_token_auth(monkeypatch):
    """Vérifie la configuration automatique de StaticTokenAuth via PRESTD_TOKEN."""
    monkeypatch.setenv("PRESTD_TOKEN", "jwt_token_123")
    client = PrestdClient()
    assert isinstance(client._auth, StaticTokenAuth)
    headers = await client._auth.get_headers()
    assert headers == {"Authorization": "Bearer jwt_token_123"}
    await client.close()


@pytest.mark.asyncio
async def test_connector_jwt_auth(monkeypatch):
    """Vérifie la configuration automatique de JWTAuth."""
    monkeypatch.delenv("PRESTD_TOKEN", raising=False)
    monkeypatch.setenv("PRESTD_USERNAME", "admin")
    monkeypatch.setenv("PRESTD_PASSWORD", "secret")
    client = PrestdClient()
    assert isinstance(client._auth, JWTAuth)
    await client.close()


@pytest.mark.asyncio
async def test_connector_keycloak_auth(monkeypatch):
    """Vérifie la configuration automatique de KeycloakAuth."""
    monkeypatch.setenv("KEYCLOAK_SERVER_URL", "http://keycloak:8080")
    monkeypatch.setenv("PRESTD_USERNAME", "alice")
    monkeypatch.setenv("PRESTD_PASSWORD", "secret")
    client = PrestdClient()
    assert isinstance(client._auth, KeycloakAuth)
    await client.close()


@pytest.mark.asyncio
@respx.mock
async def test_connector_executes_query():
    """Vérifie que PrestdClient de prestd_connector exécute nativement les requêtes table."""
    respx.get("http://localhost:3000/testdb/public/users?active=$eq.true").mock(
        return_value=Response(200, json=[{"id": 1, "name": "Alice"}])
    )

    async with PrestdClient(default_database="testdb") as client:
        rows = await client.table("users").eq("active", True).execute()
        assert rows == [{"id": 1, "name": "Alice"}]
