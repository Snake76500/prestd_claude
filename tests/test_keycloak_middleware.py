import time
from typing import Any

import httpx
import jwt
import pytest
import respx
from httpx import ASGITransport

from service.config import Settings
from service.main import create_app
from service.security import KeycloakValidator, UserContext, check_table_permission, resolve_action

SECRET_KEY = "test-secret-key-12345678901234567890"


def generate_token(
    roles: list[str] | None = None,
    client_roles: dict[str, list[str]] | None = None,
    permissions: list[dict[str, Any]] | None = None,
    sub: str = "user-123",
    username: str = "testuser",
    expired: bool = False,
    secret: str = SECRET_KEY,
) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": sub,
        "preferred_username": username,
        "email": f"{username}@example.com",
        "iat": now - 60,
        "exp": now - 10 if expired else now + 3600,
        "realm_access": {"roles": roles or []},
    }
    if client_roles:
        payload["resource_access"] = {
            client: {"roles": r} for client, r in client_roles.items()
        }
    if permissions:
        payload["authorization"] = {"permissions": permissions}

    return jwt.encode(payload, secret, algorithm="HS256")


# ==============================================================================
# Unit Tests : UserContext & check_table_permission
# ==============================================================================


def test_user_context_parsing():
    token = generate_token(
        roles=["user", "users:read"],
        client_roles={"my-client": ["orders:write"]},
        permissions=[{"rsname": "products", "scopes": ["read"]}],
    )
    payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
    ctx = UserContext(payload)

    assert ctx.user_id == "user-123"
    assert ctx.username == "testuser"
    assert "users:read" in ctx.roles
    assert "orders:write" in ctx.roles
    assert len(ctx.permissions) == 1
    assert ctx.permissions[0]["rsname"] == "products"


def test_check_table_permission_admin():
    ctx = UserContext({"realm_access": {"roles": ["admin"]}})
    assert check_table_permission(ctx, "users", "read") is True
    assert check_table_permission(ctx, "users", "write") is True
    assert check_table_permission(ctx, "any_table", "delete") is True


def test_check_table_permission_granular_roles():
    ctx = UserContext({"realm_access": {"roles": ["users:read", "orders:write"]}})

    # Lecture sur users -> OK
    assert check_table_permission(ctx, "users", "read") is True
    # Écriture sur users -> KO
    assert check_table_permission(ctx, "users", "write") is False
    # Suppression sur users -> KO
    assert check_table_permission(ctx, "users", "delete") is False

    # Écriture sur orders -> OK
    assert check_table_permission(ctx, "orders", "write") is True
    # Suppression sur orders (couvert par write) -> OK
    assert check_table_permission(ctx, "orders", "delete") is True
    # Lecture sur orders -> KO
    assert check_table_permission(ctx, "orders", "read") is False


def test_check_table_permission_wildcard():
    # Wildcard sur une table
    ctx_table_wildcard = UserContext({"realm_access": {"roles": ["users:*"]}})
    assert check_table_permission(ctx_table_wildcard, "users", "read") is True
    assert check_table_permission(ctx_table_wildcard, "users", "write") is True
    assert check_table_permission(ctx_table_wildcard, "orders", "read") is False

    # Wildcard sur toutes les tables en lecture
    ctx_action_wildcard = UserContext({"realm_access": {"roles": ["*:read"]}})
    assert check_table_permission(ctx_action_wildcard, "users", "read") is True
    assert check_table_permission(ctx_action_wildcard, "orders", "read") is True
    assert check_table_permission(ctx_action_wildcard, "users", "write") is False


def test_check_table_permission_uma_structure():
    ctx = UserContext(
        {
            "authorization": {
                "permissions": [
                    {"rsname": "customers", "scopes": ["read", "write"]},
                    {"rsname": "invoices", "scopes": ["read"]},
                ]
            }
        }
    )
    assert check_table_permission(ctx, "customers", "read") is True
    assert check_table_permission(ctx, "customers", "write") is True
    assert check_table_permission(ctx, "invoices", "read") is True
    assert check_table_permission(ctx, "invoices", "write") is False


def test_resolve_action():
    assert resolve_action("GET") == "read"
    assert resolve_action("POST") == "write"
    assert resolve_action("PATCH") == "write"
    assert resolve_action("PUT") == "write"
    assert resolve_action("DELETE") == "delete"


# ==============================================================================
# Integration Tests : Middleware FastAPI
# ==============================================================================


@pytest.fixture
async def app():
    # App avec clé Keycloak configurée
    test_settings = Settings(
        prestd_base_url="http://prestd-mock:3000",
        prestd_database="prest",
        prestd_schema="public",
        keycloak_enabled=True,
        keycloak_public_key=SECRET_KEY,
        keycloak_algorithms=["HS256"],
    )
    from service import config

    orig_settings = config.settings
    config.settings = test_settings
    application = create_app()

    from prestd_client import PrestdClient

    mock_client = PrestdClient(
        test_settings.prestd_base_url,
        default_database=test_settings.prestd_database,
        default_schema=test_settings.prestd_schema,
    )
    application.state.prestd_client = mock_client
    try:
        yield application
    finally:
        await mock_client.close()
        config.settings = orig_settings


@pytest.mark.asyncio
async def test_public_endpoint_bypasses_keycloak(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_table_endpoint_missing_token_returns_401(app):
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/tables/users")
        assert response.status_code == 401
        assert "Authorization header missing" in response.json()["error"]


@pytest.mark.asyncio
async def test_table_endpoint_expired_token_returns_401(app):
    token = generate_token(roles=["users:read"], expired=True)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/tables/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 401
        assert "expired" in response.json()["error"].lower()


@pytest.mark.asyncio
async def test_table_endpoint_insufficient_permissions_returns_403(app):
    # L'utilisateur n'a le droit que de lire la table `orders`, pas `users`
    token = generate_token(roles=["orders:read"])
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/tables/users", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 403
        data = response.json()
        assert "Permission denied" in data["error"]
        assert data["table"] == "users"
        assert data["action"] == "read"


@pytest.mark.asyncio
async def test_table_endpoint_read_permission_allows_get(app):
    token = generate_token(roles=["users:read"])
    transport = ASGITransport(app=app)

    with respx.mock(base_url="http://prestd-mock:3000") as prest_mock:
        prest_mock.get("/prest/public/users").mock(
            return_value=httpx.Response(200, json=[{"id": 1, "name": "Alice"}])
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/tables/users", headers={"Authorization": f"Bearer {token}"})
            assert response.status_code == 200
            assert response.json() == [{"id": 1, "name": "Alice"}]


@pytest.mark.asyncio
async def test_table_endpoint_read_permission_forbids_post(app):
    token = generate_token(roles=["users:read"])
    transport = ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/tables/users",
            json={"name": "Bob"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 403
        assert "Permission denied for action 'write' on table 'users'" in response.json()["error"]


@pytest.mark.asyncio
async def test_table_endpoint_write_permission_allows_post(app):
    token = generate_token(roles=["users:write"])
    transport = ASGITransport(app=app)

    with respx.mock(base_url="http://prestd-mock:3000") as prest_mock:
        prest_mock.post("/prest/public/users").mock(
            return_value=httpx.Response(201, json={"id": 2, "name": "Bob"})
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/tables/users",
                json={"name": "Bob"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 201
            assert response.json() == {"id": 2, "name": "Bob"}


@pytest.mark.asyncio
async def test_table_endpoint_delete_permission_allows_delete(app):
    token = generate_token(roles=["users:delete"])
    transport = ASGITransport(app=app)

    with respx.mock(base_url="http://prestd-mock:3000") as prest_mock:
        prest_mock.delete("/prest/public/users?id=2").mock(
            return_value=httpx.Response(200, json={"deleted": 1})
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.delete(
                "/tables/users?id=2",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200


@pytest.mark.asyncio
async def test_table_endpoint_admin_allows_all(app):
    token = generate_token(roles=["admin"])
    transport = ASGITransport(app=app)

    with respx.mock(base_url="http://prestd-mock:3000") as prest_mock:
        prest_mock.get("/prest/public/secret_table").mock(
            return_value=httpx.Response(200, json=[{"id": 99}])
        )
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/tables/secret_table",
                headers={"Authorization": f"Bearer {token}"},
            )
            assert response.status_code == 200
            assert response.json() == [{"id": 99}]
