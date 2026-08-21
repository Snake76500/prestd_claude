"""Test et exemple de bout en bout (E2E) :
1. Récupération d'un token JWT auprès de Keycloak (OpenID Connect Password Grant / Direct Access Grants).
2. Exécution d'une requête SELECT (GET /tables/{table}) sur le microservice avec ce token.

Ce fichier peut être :
- Lancé directement avec Python : `python tests/test_keycloak_flow.py`
- Exécuté dans la suite de tests automatisés : `pytest tests/test_keycloak_flow.py`
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import pytest
import respx
from httpx import ASGITransport

# ==============================================================================
# Paramètres de connexion Keycloak & Microservice (configurables via variables d'environnement)
# ==============================================================================

KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_REALM = os.getenv("KEYCLOAK_REALM", "master")
KEYCLOAK_CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "prestd-service")
KEYCLOAK_CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", None)
KEYCLOAK_USERNAME = os.getenv("KEYCLOAK_USERNAME", "testuser")
KEYCLOAK_PASSWORD = os.getenv("KEYCLOAK_PASSWORD", "testpass")
KEYCLOAK_VERIFY_SSL = os.getenv("KEYCLOAK_VERIFY_SSL", "false").lower() in ("true", "1", "yes")

SERVICE_BASE_URL = os.getenv("SERVICE_BASE_URL", "http://localhost:8000")


async def get_keycloak_token(
    server_url: str = KEYCLOAK_URL,
    realm: str = KEYCLOAK_REALM,
    client_id: str = KEYCLOAK_CLIENT_ID,
    username: str = KEYCLOAK_USERNAME,
    password: str = KEYCLOAK_PASSWORD,
    client_secret: str | None = KEYCLOAK_CLIENT_SECRET,
    verify_ssl: bool = KEYCLOAK_VERIFY_SSL,
) -> str:
    """Récupère un JWT Access Token auprès de Keycloak (OIDC Resource Owner Password Credentials)."""
    token_endpoint = f"{server_url.rstrip('/')}/realms/{realm}/protocol/openid-connect/token"

    payload: dict[str, str] = {
        "grant_type": "password",
        "client_id": client_id,
        "username": username,
        "password": password,
    }
    if client_secret:
        payload["client_secret"] = client_secret

    async with httpx.AsyncClient(verify=verify_ssl) as client:
        response = await client.post(
            token_endpoint,
            data=payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10.0,
        )

        if response.status_code != 200:
            raise RuntimeError(
                f"Échec de l'authentification Keycloak (HTTP {response.status_code}) : {response.text}"
            )

        data = response.json()
        token = data.get("access_token")
        if not token:
            raise ValueError(f"La réponse Keycloak ne contient pas d'access_token : {data}")

        return token


async def select_table(
    table: str,
    token: str,
    service_url: str = SERVICE_BASE_URL,
    params: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Exécute un SELECT (GET /tables/{table}) sur le microservice en passant le Bearer token Keycloak."""
    endpoint = f"{service_url.rstrip('/')}/tables/{table}"

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(endpoint, headers=headers, params=params, timeout=10.0)

        if response.status_code == 401:
            raise PermissionError(f"401 Unauthorized : token invalide ou expiré ({response.text})")
        if response.status_code == 403:
            raise PermissionError(
                f"403 Forbidden : droits insuffisants pour lire la table '{table}' ({response.text})"
            )
        payload = response.json()
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload


# ==============================================================================
# Test automatisé Pytest (avec mock Keycloak + Prestd)
# ==============================================================================


@pytest.mark.asyncio
async def test_keycloak_auth_and_select_flow():
    """Valide le flux complet :
    1. Récupération du JWT sur le endpoint OpenID Connect de Keycloak
    2. Appel GET /tables/users avec le header Authorization: Bearer <token>
    3. Réception des données de la table
    """
    import time
    import jwt
    from service.config import Settings
    from service.main import create_app
    from prestd_client import PrestdClient

    secret_key = "test-secret-key-12345678901234567890"

    # Création d'un token JWT simulant Keycloak
    now = int(time.time())
    simulated_jwt = jwt.encode(
        {
            "sub": "keycloak-user-001",
            "preferred_username": "fabien",
            "realm_access": {"roles": ["users:read"]},
            "iat": now,
            "exp": now + 3600,
        },
        secret_key,
        algorithm="HS256",
    )

    # Mock du serveur Keycloak
    with respx.mock(assert_all_called=False) as mock:
        mock.post(f"{KEYCLOAK_URL}/realms/{KEYCLOAK_REALM}/protocol/openid-connect/token").mock(
            return_value=httpx.Response(
                200,
                json={
                    "access_token": simulated_jwt,
                    "token_type": "Bearer",
                    "expires_in": 3600,
                },
            )
        )

        # Mock de prestd en amont
        mock.get("http://prestd-mock:3000/prest/public/users").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": 1, "name": "Fabien", "active": True},
                    {"id": 2, "name": "Reynald", "active": True},
                ],
            )
        )

        # 1. Récupération du token auprès de Keycloak
        token = await get_keycloak_token(
            server_url=KEYCLOAK_URL,
            realm=KEYCLOAK_REALM,
            client_id=KEYCLOAK_CLIENT_ID,
            username="fabien",
            password="secretpassword",
        )
        assert token == simulated_jwt

        # 2. Configuration et test sur l'application FastAPI
        test_settings = Settings(
            prestd_base_url="http://prestd-mock:3000",
            prestd_database="prest",
            prestd_schema="public",
            keycloak_enabled=True,
            keycloak_public_key=secret_key,
            keycloak_algorithms=["HS256"],
        )
        from service import config

        orig_settings = config.settings
        config.settings = test_settings
        app = create_app()

        mock_client = PrestdClient(
            test_settings.prestd_base_url,
            default_database=test_settings.prestd_database,
            default_schema=test_settings.prestd_schema,
        )
        app.state.prestd_client = mock_client

        try:
            transport = ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                response = await client.get(
                    "/tables/users",
                    headers={"Authorization": f"Bearer {token}"},
                )
                payload = response.json()
                rows = payload["data"]
                assert len(rows) == 2
                assert rows[0]["name"] == "Fabien"
        finally:
            await mock_client.close()
            config.settings = orig_settings


# ==============================================================================
# Point d'entrée pour exécution directe (`python tests/test_keycloak_flow.py`)
# ==============================================================================


async def main():
    print("=" * 60)
    print("🚀 Test de flux : Keycloak Auth -> SELECT sur table")
    print("=" * 60)
    print(f"Keycloak URL  : {KEYCLOAK_URL}")
    print(f"Realm         : {KEYCLOAK_REALM}")
    print(f"Client ID     : {KEYCLOAK_CLIENT_ID}")
    print(f"Username      : {KEYCLOAK_USERNAME}")
    print(f"Service URL   : {SERVICE_BASE_URL}")
    print("-" * 60)

    try:
        print("\n1. 🔑 Récupération du token auprès de Keycloak...")
        token = await get_keycloak_token()
        print(f"   ✅ Token JWT obtenu (longueur: {len(token)} caractères)")
        print(f"   Token : {token[:20]}...{token[-20:]}")

        print("\n2. 📊 Exécution du SELECT sur la table 'users'...")
        rows = await select_table("users", token=token)
        print(f"   ✅ Succès ! {len(rows)} ligne(s) récupérée(s) :")
        for row in rows:
            print(f"      - {row}")

    except Exception as exc:
        print(f"\n❌ Erreur : {exc}")


if __name__ == "__main__":
    asyncio.run(main())
