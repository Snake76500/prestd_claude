"""Validation et décodage des tokens JWT émis par Keycloak."""
from __future__ import annotations

import logging
from typing import Any

import jwt
from jwt.exceptions import PyJWTError

from ..config import Settings, settings

logger = logging.getLogger("prestd_service.security.keycloak")


def _format_public_key(key: str) -> str:
    """Normalise la clé publique Keycloak en format PEM valide."""
    cleaned = key.strip()
    if "-----BEGIN PUBLIC KEY-----" in cleaned or "-----BEGIN CERTIFICATE-----" in cleaned:
        return cleaned
    # Si Keycloak fournit une chaîne base64 brute sans en-tête PEM
    lines = [cleaned[i : i + 64] for i in range(0, len(cleaned), 64)]
    return "-----BEGIN PUBLIC KEY-----\n" + "\n".join(lines) + "\n-----END PUBLIC KEY-----"


class KeycloakValidator:
    """Valide les JWT Keycloak avec support des clés publiques PEM, secrets HMAC ou mode permissif si configuré."""

    def __init__(self, app_settings: Settings | None = None) -> None:
        self.settings = app_settings or settings

    def get_verification_key(self, token: str) -> str | None:
        """Retourne la clé de vérification configurée."""
        if self.settings.keycloak_public_key:
            return _format_public_key(self.settings.keycloak_public_key)
        return None

    def decode_token(self, token: str) -> dict[str, Any]:
        """Décode et valide un JWT Keycloak.

        Lève PyJWTError ou ValueError si le token est invalide ou expiré.
        """
        key = self.get_verification_key(token)
        algorithms = self.settings.keycloak_algorithms

        options = {
            "verify_signature": key is not None,
            "verify_exp": True,
            "verify_aud": self.settings.keycloak_audience is not None,
        }

        decode_kwargs: dict[str, Any] = {
            "algorithms": algorithms,
            "options": options,
        }
        if self.settings.keycloak_audience:
            decode_kwargs["audience"] = self.settings.keycloak_audience

        if key is not None:
            return jwt.decode(token, key, **decode_kwargs)
        else:
            # Si aucune clé n'est configurée (ex: environnement dev / mock),
            # on décode le payload sans vérifier la signature tout en vérifiant l'expiration
            logger.warning("Aucune clé publique Keycloak configurée. Validation de signature désactivée.")
            return jwt.decode(token, options={"verify_signature": False, "verify_exp": True})


class UserContext:
    """Représentation structurée de l'utilisateur authentifié et de ses droits."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.user_id: str = payload.get("sub", "")
        self.username: str = payload.get("preferred_username", payload.get("username", ""))
        self.email: str = payload.get("email", "")

        # Agrégation des rôles (realm_access + resource_access)
        roles: set[str] = set()
        realm_access = payload.get("realm_access") or {}
        if isinstance(realm_access, dict):
            roles.update(realm_access.get("roles", []))

        resource_access = payload.get("resource_access") or {}
        if isinstance(resource_access, dict):
            for client_data in resource_access.values():
                if isinstance(client_data, dict):
                    roles.update(client_data.get("roles", []))

        # Support direct d'un tableau 'roles' dans le payload
        if isinstance(payload.get("roles"), list):
            roles.update(payload["roles"])

        self.roles = roles

        # Permissions Keycloak UMA / Authorization Services
        # Format attendu : authorization.permissions = [{"rsname": "users", "scopes": ["read", "write"]}]
        self.permissions: list[dict[str, Any]] = []
        auth_data = payload.get("authorization") or {}
        if isinstance(auth_data, dict):
            perms = auth_data.get("permissions") or []
            if isinstance(perms, list):
                self.permissions = perms

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "roles": list(self.roles),
            "permissions": self.permissions,
        }
