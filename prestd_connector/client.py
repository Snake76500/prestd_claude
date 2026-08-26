"""Client enrichi héritant directement de prestd_client.PrestdClient."""
from __future__ import annotations

import os
from typing import Any, Sequence

import httpx
from prestd_client import (
    BaseAuth,
    JWTAuth,
    KeycloakAuth,
    PrestdClient as BasePrestdClient,
    StaticTokenAuth,
    SyncPrestdClient as BaseSyncPrestdClient,
)


class PrestdClient(BasePrestdClient):
    """Client asynchrone prestd avec résolution automatique de la configuration.

    Hérite à 100% de `prestd_client.PrestdClient` : toutes les méthodes
    (`.table()`, `.insert()`, `.update()`, `.delete()`, `.get_tables()`, etc.)
    sont disponibles nativement sans duplication de code.
    """

    def __init__(
        self,
        base_url: str | None = None,
        *,
        default_database: str | None = None,
        default_schema: str = "public",
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        keycloak_url: str | None = None,
        keycloak_realm: str | None = None,
        keycloak_client_id: str | None = None,
        auth: BaseAuth | None = None,
        timeout: float = 30.0,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        verify_permissions: bool = True,
        admin_roles: Sequence[str] | None = None,
        default_page_size: int | None = None,
        max_page_size: int | None = None,
        **kwargs: Any,
    ) -> None:
        # 1. Résolution de l'URL et de la base de données (arguments OU variables d'environnement)
        resolved_url = (
            base_url
            or os.getenv("PRESTD_URL")
            or os.getenv("PRESTD_BASE_URL")
            or "http://localhost:3000"
        )
        resolved_db = (
            default_database
            or os.getenv("PRESTD_DATABASE")
            or os.getenv("PRESTD_DB")
        )
        resolved_schema = (
            default_schema
            if default_schema != "public"
            else (os.getenv("PRESTD_SCHEMA") or "public")
        )

        # 2. Résolution automatique de la stratégie d'authentification
        resolved_auth = auth
        if resolved_auth is None:
            jwt_token = token or os.getenv("PRESTD_TOKEN")
            kc_url = keycloak_url or os.getenv("KEYCLOAK_SERVER_URL")
            user = username or os.getenv("PRESTD_USERNAME")
            pwd = password or os.getenv("PRESTD_PASSWORD")

            if kc_url and user and pwd:
                resolved_auth = KeycloakAuth(
                    server_url=kc_url,
                    realm=keycloak_realm or os.getenv("KEYCLOAK_REALM", "master"),
                    client_id=keycloak_client_id or os.getenv("KEYCLOAK_CLIENT_ID", "prestd"),
                    username=user,
                    password=pwd,
                )
            elif jwt_token:
                resolved_auth = StaticTokenAuth(jwt_token)
            elif user and pwd:
                resolved_auth = JWTAuth(user, pwd)

        # 3. Initialisation de la classe de base prestd_client
        super().__init__(
            base_url=resolved_url,
            default_database=resolved_db,
            default_schema=resolved_schema,
            timeout=timeout,
            verify=verify,
            transport=transport,
            auth=resolved_auth,
            keycloak_token=token if isinstance(resolved_auth, KeycloakAuth) else None,
            verify_permissions=verify_permissions,
            admin_roles=admin_roles,
            default_page_size=default_page_size,
            max_page_size=max_page_size,
            **kwargs,
        )

    @classmethod
    def from_env(cls, **kwargs: Any) -> "PrestdClient":
        """Constructeur explicite depuis l'environnement."""
        return cls(**kwargs)


class SyncPrestdClient(BaseSyncPrestdClient):
    """Client synchrone prestd avec résolution automatique de la configuration."""

    def __init__(
        self,
        base_url: str | None = None,
        *,
        default_database: str | None = None,
        default_schema: str = "public",
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
        keycloak_url: str | None = None,
        keycloak_realm: str | None = None,
        keycloak_client_id: str | None = None,
        auth: BaseAuth | None = None,
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        async_client = PrestdClient(
            base_url=base_url,
            default_database=default_database,
            default_schema=default_schema,
            token=token,
            username=username,
            password=password,
            keycloak_url=keycloak_url,
            keycloak_realm=keycloak_realm,
            keycloak_client_id=keycloak_client_id,
            auth=auth,
            timeout=timeout,
            **kwargs,
        )
        super().__init__(
            base_url=async_client.base_url,
            default_database=async_client.default_database,
            default_schema=async_client.default_schema,
            auth=async_client._auth,
            timeout=async_client._http.timeout.read or 30.0,
            verify_permissions=async_client.verify_permissions,
            admin_roles=async_client.admin_roles,
            default_page_size=async_client.default_page_size,
            max_page_size=async_client.max_page_size,
        )
