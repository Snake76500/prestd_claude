"""Tests unitaires pour la gestion de Keycloak et la vérification des permissions RBAC dans le SDK prestd_client."""
from __future__ import annotations

import base64
import json
from typing import Any

import pytest
import respx
from httpx import Response

from prestd_client import (
    KeycloakAuth,
    PrestdClient,
    PrestdPermissionError,
    SyncPrestdClient,
)


def _make_dummy_jwt(
    username: str = "alice",
    realm_roles: list[str] | None = None,
    client_roles: dict[str, list[str]] | None = None,
    direct_roles: list[str] | None = None,
    uma_permissions: list[dict[str, Any]] | None = None,
) -> str:
    """Génère un JWT factice non signé mais valide pour l'extraction de payload."""
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none", "typ": "JWT"}).encode()).decode().rstrip("=")
    payload_data: dict[str, Any] = {
        "sub": "user-12345",
        "preferred_username": username,
        "email": f"{username}@example.com",
        "realm_access": {"roles": realm_roles or []},
        "resource_access": client_roles or {},
    }
    if direct_roles:
        payload_data["roles"] = direct_roles
    if uma_permissions:
        payload_data["authorization"] = {"permissions": uma_permissions}

    payload = base64.urlsafe_b64encode(json.dumps(payload_data).encode()).decode().rstrip("=")
    return f"{header}.{payload}.signature"


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_client_read_allowed():
    """Vérifie que l'utilisateur ayant le rôle 'users:read' peut exécuter un SELECT (GET)."""
    token = _make_dummy_jwt(username="reader", realm_roles=["users:read"])
    respx.get("http://prestd:3000/prest/public/users").mock(
        return_value=Response(200, json=[{"id": 1, "name": "Alice"}])
    )

    async with PrestdClient("http://prestd:3000", default_database="prest", auth=KeycloakAuth(token)) as client:
        assert client.current_user.username == "reader"
        assert client.has_table_permission("users", "read") is True
        assert client.has_table_permission("users", "write") is False

        rows = await client.table("users").execute()
        assert rows == [{"id": 1, "name": "Alice"}]


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_client_read_denied():
    """Vérifie qu'une tentative de SELECT (GET) sans droit 'read' lève PrestdPermissionError (403)."""
    # L'utilisateur a seulement 'orders:read', mais tente d'accéder à 'users'
    token = _make_dummy_jwt(username="bob", realm_roles=["orders:read"])

    async with PrestdClient("http://prestd:3000", default_database="prest", keycloak_token=token) as client:
        assert client.has_table_permission("users", "read") is False

        with pytest.raises(PrestdPermissionError) as exc_info:
            await client.table("users").execute()

        assert exc_info.value.status_code == 403
        assert "Permission denied for action 'read' on table 'users'" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_client_insert_allowed_and_denied():
    """Vérifie les droits sur l'action INSERT (POST / write)."""
    respx.post("http://prestd:3000/prest/public/users").mock(
        return_value=Response(201, json={"id": 2, "name": "Bob"})
    )

    # 1. Avec droit 'users:write' -> Succès
    writer_token = _make_dummy_jwt(username="writer", realm_roles=["users:write"])
    async with PrestdClient("http://prestd:3000", default_database="prest", auth=KeycloakAuth(writer_token)) as client:
        res = await client.table("users").insert({"name": "Bob"})
        assert res == {"id": 2, "name": "Bob"}

    # 2. Avec seulement droit 'users:read' -> Échec
    reader_token = _make_dummy_jwt(username="reader_only", realm_roles=["users:read"])
    async with PrestdClient("http://prestd:3000", default_database="prest", auth=KeycloakAuth(reader_token)) as client:
        with pytest.raises(PrestdPermissionError) as exc_info:
            await client.table("users").insert({"name": "Bob"})
        assert exc_info.value.status_code == 403
        assert "Permission denied for action 'write' on table 'users'" in str(exc_info.value)


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_client_update_and_delete_permissions():
    """Vérifie les droits sur UPDATE (PATCH) et DELETE."""
    respx.patch("http://prestd:3000/prest/public/users").mock(
        return_value=Response(200, json={"id": 1, "status": "active"})
    )
    respx.delete("http://prestd:3000/prest/public/users").mock(
        return_value=Response(200, json={"deleted": 1})
    )

    # Utilisateur avec rôle 'users:delete'
    token = _make_dummy_jwt(username="deleter", realm_roles=["users:delete"])
    async with PrestdClient("http://prestd:3000", default_database="prest", keycloak_token=token) as client:
        # Delete autorisé
        del_res = await client.table("users").eq("id", 1).delete()
        assert del_res == {"deleted": 1}

        # Update refusé (n'a pas 'write')
        with pytest.raises(PrestdPermissionError):
            await client.table("users").eq("id", 1).update({"status": "active"})


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_admin_universal_access():
    """Vérifie que le rôle 'admin' donne accès à toutes les actions sur toutes les tables."""
    admin_token = _make_dummy_jwt(username="superadmin", realm_roles=["admin"])
    respx.get("http://prestd:3000/prest/public/confidential_table").mock(
        return_value=Response(200, json=[{"secret": "42"}])
    )
    respx.delete("http://prestd:3000/prest/public/confidential_table").mock(
        return_value=Response(200, json={"deleted": 1})
    )

    async with PrestdClient("http://prestd:3000", default_database="prest", keycloak_token=admin_token) as client:
        assert client.has_table_permission("confidential_table", "read") is True
        assert client.has_table_permission("confidential_table", "delete") is True

        rows = await client.table("confidential_table").execute()
        assert rows == [{"secret": "42"}]

        del_res = await client.table("confidential_table").eq("id", 1).delete()
        assert del_res == {"deleted": 1}


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_uma_permissions():
    """Vérifie le support des permissions UMA Keycloak (authorization.permissions)."""
    uma_token = _make_dummy_jwt(
        username="uma_user",
        uma_permissions=[{"rsname": "documents", "scopes": ["read"]}],
    )
    respx.get("http://prestd:3000/prest/public/documents").mock(
        return_value=Response(200, json=[{"title": "Doc 1"}])
    )

    async with PrestdClient("http://prestd:3000", default_database="prest", keycloak_token=uma_token) as client:
        assert client.has_table_permission("documents", "read") is True
        assert client.has_table_permission("documents", "delete") is False

        rows = await client.table("documents").execute()
        assert rows == [{"title": "Doc 1"}]

        with pytest.raises(PrestdPermissionError):
            await client.table("documents").eq("id", 1).delete()


@pytest.mark.asyncio
@respx.mock
async def test_keycloak_auth_dynamic_login():
    """Vérifie la récupération dynamique d'un token via KeycloakAuth."""
    respx.post("http://keycloak:8080/realms/master/protocol/openid-connect/token").mock(
        return_value=Response(200, json={"access_token": _make_dummy_jwt("dynamo", realm_roles=["users:*"])})
    )
    respx.get("http://prestd:3000/prest/public/users").mock(
        return_value=Response(200, json=[{"id": 1}])
    )

    auth = KeycloakAuth(
        server_url="http://keycloak:8080",
        realm="master",
        client_id="prestd",
        username="alice",
        password="pwd",
    )
    async with PrestdClient("http://prestd:3000", default_database="prest", auth=auth) as client:
        rows = await client.table("users").execute()
        assert rows == [{"id": 1}]
        assert client.current_user.username == "dynamo"


def test_sync_prestd_client_keycloak():
    """Vérifie le fonctionnement de SyncPrestdClient avec Keycloak."""
    with respx.mock:
        token = _make_dummy_jwt("sync_user", realm_roles=["users:read"])
        respx.get("http://prestd:3000/prest/public/users").mock(
            return_value=Response(200, json=[{"id": 100}])
        )

        with SyncPrestdClient("http://prestd:3000", default_database="prest", keycloak_token=token) as client:
            assert client.current_user.username == "sync_user"
            assert client.has_table_permission("users", "read") is True
            assert client.has_table_permission("users", "write") is False

            rows = client.table("users").execute()
            assert rows == [{"id": 100}]

            # Tentative d'insertion non autorisée
            with pytest.raises(PrestdPermissionError):
                client.table("users").insert({"name": "Forbidden"})
