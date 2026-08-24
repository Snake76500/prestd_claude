"""Exemple de SELECT sur une table en utilisant le SDK Python `prestd_client` avec authentification Keycloak.

Ce script illustre :
1. La récupération d'un Access Token JWT auprès de Keycloak (Resource Owner Password Credentials).
2. L'inspection des rôles applicatifs dans le token.
3. L'utilisation du SDK `PrestdClient` (asynchrone) et de `SyncPrestdClient` (synchrone) avec `StaticTokenAuth`.
4. La construction fluide de requêtes SQL via `QueryBuilder` (.select(), .eq(), .page(), .order_by(), .execute()).
5. La gestion propre des erreurs de sécurité du microservice (PrestdError : 401 Unauthorized / 403 Forbidden).

Utilisation :
    python tests/example_keycloak_select.py
"""
from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx
import jwt

# Import du SDK développé dans ce projet
from prestd_client import (
    PrestdAuthError,
    PrestdClient,
    PrestdError,
    StaticTokenAuth,
    SyncPrestdClient,
)

# ==============================================================================
# Paramètres de configuration (surchargeables via variables d'environnement)
# ==============================================================================
KEYCLOAK_URL = os.getenv("KEYCLOAK_URL", "http://localhost:8080")
REALM = os.getenv("KEYCLOAK_REALM", "master")
CLIENT_ID = os.getenv("KEYCLOAK_CLIENT_ID", "prestd-service")
CLIENT_SECRET = os.getenv("KEYCLOAK_CLIENT_SECRET", None)
USERNAME = os.getenv("KEYCLOAK_USERNAME", "alice")
PASSWORD = os.getenv("KEYCLOAK_PASSWORD", "secretpassword")
VERIFY_SSL = os.getenv("KEYCLOAK_VERIFY_SSL", "false").lower() in ("true", "1", "yes")

SERVICE_URL = os.getenv("SERVICE_BASE_URL", "http://localhost:8000")
TABLE_NAME = os.getenv("TABLE_NAME", "users")


async def get_keycloak_token() -> str:
    """Récupère l'Access Token JWT auprès de Keycloak."""
    token_endpoint = f"{KEYCLOAK_URL.rstrip('/')}/realms/{REALM}/protocol/openid-connect/token"
    payload = {
        "grant_type": "password",
        "client_id": CLIENT_ID,
        "username": USERNAME,
        "password": PASSWORD,
    }
    if CLIENT_SECRET:
        payload["client_secret"] = CLIENT_SECRET

    print(f"1. Demande de token auprès de Keycloak pour l'utilisateur '{USERNAME}'...")
    async with httpx.AsyncClient(verify=VERIFY_SSL) as http_client:
        resp = await http_client.post(token_endpoint, data=payload)
        if resp.status_code != 200:
            raise RuntimeError(f"Échec Keycloak ({resp.status_code}) : {resp.text}")
        token = resp.json()["access_token"]
        print("✅ Token JWT obtenu avec succès !\n")
        return token


def inspect_token(token: str) -> None:
    """Décode et affiche l'utilisateur et les rôles contenus dans le token."""
    claims: dict[str, Any] = jwt.decode(token, options={"verify_signature": False})
    user = claims.get("preferred_username", claims.get("sub"))
    roles: set[str] = set()

    # Rôles Realm
    realm_access = claims.get("realm_access") or {}
    roles.update(realm_access.get("roles", []))

    # Rôles Client
    resource_access = claims.get("resource_access") or {}
    for client_data in resource_access.values():
        if isinstance(client_data, dict):
            roles.update(client_data.get("roles", []))

    print(f"2. Utilisateur identifié dans le JWT : {user}")
    print(f"   Rôles extraits du token           : {sorted(roles)}\n")


async def async_select_with_sdk(token: str) -> None:
    """Exécution d'un SELECT via le client ASYNCHRONE PrestdClient."""
    print(f"3. [Async] Initialisation de PrestdClient avec StaticTokenAuth...")

    # 1. Instanciation du client avec la stratégie d'authentification par token Keycloak
    async with PrestdClient(base_url=SERVICE_URL, auth=StaticTokenAuth(token)) as client:
        try:
            print(f"   Exécution : client.table('{TABLE_NAME}').select('*').page(1, page_size=5).execute()")

            # 2. Construction fluide de la requête
            rows = await (
                client.table(TABLE_NAME)
                .select("*")
                .page(page=1, page_size=5)
                .order_by("-id")
                .execute()
            )

            print(f"   ✅ [Async] SELECT réussi ! ({len(rows)} enregistrement(s) retourné(s)) :")
            for row in rows:
                print(f"      - {row}")

        except PrestdError as exc:
            if exc.status_code == 403:
                print(f"   ⛔ 403 Forbidden : L'utilisateur n'a pas les droits pour lire '{TABLE_NAME}'.")
            elif exc.status_code == 401:
                print("   🔒 401 Unauthorized : Token invalide ou expiré.")
            else:
                print(f"   ❌ Erreur prestd ({exc.status_code}) : {exc.message}")


def sync_select_with_sdk(token: str) -> None:
    """Exécution d'un SELECT via le client SYNCHRONE SyncPrestdClient."""
    print(f"\n4. [Sync] Initialisation de SyncPrestdClient...")

    with SyncPrestdClient(base_url=SERVICE_URL, auth=StaticTokenAuth(token)) as client:
        try:
            rows = (
                client.table(TABLE_NAME)
                .page(1, 5)
                .execute()
            )
            print(f"   ✅ [Sync] SELECT réussi ! ({len(rows)} enregistrement(s))")
        except PrestdError as exc:
            print(f"   ❌ Erreur SDK synchrone ({exc.status_code}) : {exc.message}")


async def main() -> None:
    try:
        # Étape 1 : Récupérer le token Keycloak
        token = await get_keycloak_token()

        # Étape 2 : Inspecter les rôles Keycloak
        inspect_token(token)

        # Étape 3 : SELECT asynchrone avec le SDK `PrestdClient`
        await async_select_with_sdk(token)

        # Étape 4 : SELECT synchrone avec le SDK `SyncPrestdClient`
        sync_select_with_sdk(token)

    except Exception as exc:
        print(f"❌ Erreur générale : {exc}")


if __name__ == "__main__":
    asyncio.run(main())
