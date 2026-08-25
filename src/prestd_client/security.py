"""Module de sécurité et gestion des permissions pour le SDK prestd_client."""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Sequence, Set

logger = logging.getLogger("prestd_client.security")

DEFAULT_ADMIN_ROLES = ["admin", "realm-admin", "superuser"]

HTTP_METHOD_ACTION_MAP = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "read",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "delete",
}


def decode_jwt_payload_unverified(token: str) -> dict[str, Any]:
    """Décode la charge utile (payload) d'un token JWT sans validation cryptographique de signature.

    Permet au client d'extraire rapidement les claims et rôles pour vérifier
    les permissions avant d'émettre la requête HTTP.
    """
    if not token or not isinstance(token, str):
        return {}
    parts = token.strip().split(".")
    if len(parts) < 2:
        return {}
    payload_b64 = parts[1]
    # Ajout du padding base64 manquant si nécessaire
    rem = len(payload_b64) % 4
    if rem > 0:
        payload_b64 += "=" * (4 - rem)
    try:
        raw_bytes = base64.urlsafe_b64decode(payload_b64)
        return json.loads(raw_bytes.decode("utf-8"))
    except Exception as exc:
        logger.debug(f"Impossible de décoder le payload JWT: {exc}")
        return {}


class UserContext:
    """Représentation structurée de l'utilisateur et de ses permissions extraits d'un token Keycloak."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.user_id: str = str(payload.get("sub", ""))
        self.username: str = str(payload.get("preferred_username", payload.get("username", "")))
        self.email: str = str(payload.get("email", ""))

        roles: set[str] = set()

        # Realm roles
        realm_access = payload.get("realm_access") or {}
        if isinstance(realm_access, dict):
            roles.update(realm_access.get("roles", []))

        # Client / Resource roles
        resource_access = payload.get("resource_access") or {}
        if isinstance(resource_access, dict):
            for client_data in resource_access.values():
                if isinstance(client_data, dict):
                    roles.update(client_data.get("roles", []))

        # Tableau direct roles
        if isinstance(payload.get("roles"), list):
            roles.update(payload["roles"])

        self.roles = roles

        # Permissions UMA (authorization.permissions)
        self.permissions: list[dict[str, Any]] = []
        auth_data = payload.get("authorization") or {}
        if isinstance(auth_data, dict):
            perms = auth_data.get("permissions") or []
            if isinstance(perms, list):
                self.permissions = perms

    def has_role(self, role: str) -> bool:
        return role.lower() in {r.lower() for r in self.roles}

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "email": self.email,
            "roles": list(self.roles),
            "permissions": self.permissions,
        }

    def __repr__(self) -> str:
        return f"<UserContext username={self.username!r} roles={list(self.roles)!r}>"


def resolve_action(http_method: str) -> str:
    """Traduit une méthode HTTP en action générique (`read`, `write`, `delete`)."""
    return HTTP_METHOD_ACTION_MAP.get(http_method.upper(), "read")


def check_table_permission(
    user: UserContext,
    table: str,
    action: str,
    admin_roles: Sequence[str] | None = None,
) -> bool:
    """Vérifie si l'utilisateur possède le droit d'exécuter `action` sur `table`.

    Vérifie successivement :
    1. Rôle d'administration global (ex: 'admin', 'realm-admin', 'superuser')
    2. Rôle granulaire 'table:action' (ex: 'users:read', 'orders:write', 'users:*', '*:read', '*')
    3. Permission UMA Keycloak (resource_name = table, scopes contenant action)
    """
    admin_roles_set = {r.lower() for r in (admin_roles or DEFAULT_ADMIN_ROLES)}
    user_roles_lower = {r.lower() for r in user.roles}

    # 1. Vérification des rôles d'administration
    if any(role in admin_roles_set for role in user_roles_lower):
        return True

    # 2. Vérification des rôles granulaires
    action_lower = action.lower()
    compatible_actions: Set[str] = {action_lower, "*"}
    if action_lower in ("delete", "create", "update"):
        compatible_actions.add("write")

    table_lower = table.lower()
    for role in user_roles_lower:
        if ":" in role:
            res, act = role.split(":", 1)
            if (res == table_lower or res == "*") and act in compatible_actions:
                return True
        elif role == "*" or role == table_lower:
            return True

    # 3. Permissions UMA (authorization.permissions)
    for perm in user.permissions:
        rsname = str(perm.get("rsname", "")).lower()
        scopes = [str(s).lower() for s in perm.get("scopes", [])]
        if rsname == table_lower or rsname == "*":
            if any(s in compatible_actions for s in scopes) or "*" in scopes or not scopes:
                return True

    return False
