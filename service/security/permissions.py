"""Vérification des permissions d'accès aux tables pour les utilisateurs Keycloak."""
from __future__ import annotations

from typing import Set

from .keycloak import UserContext

# Correspondance des méthodes HTTP vers les actions de haut niveau
HTTP_METHOD_ACTION_MAP = {
    "GET": "read",
    "HEAD": "read",
    "OPTIONS": "read",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "delete",
}

DEFAULT_ADMIN_ROLES = ["admin", "realm-admin", "superuser"]


def resolve_action(http_method: str) -> str:
    """Traduit une méthode HTTP en action de base (`read`, `write`, `delete`)."""
    return HTTP_METHOD_ACTION_MAP.get(http_method.upper(), "read")


def check_table_permission(
    user: UserContext,
    table: str,
    action: str,
    admin_roles: list[str] | None = None,
) -> bool:
    """Vérifie si l'utilisateur possède le droit d'exécuter `action` sur `table`.

    Vérifie successivement :
    1. Si l'utilisateur a un rôle d'administration global (ex: 'admin', 'superuser')
    2. Si l'utilisateur a un rôle au format 'table:action' (ex: 'users:read', 'orders:*', '*:write')
    3. Si l'utilisateur possède une permission UMA Keycloak (authorization.permissions avec rsname et scopes)
    """
    admin_roles_set = set(admin_roles or DEFAULT_ADMIN_ROLES)

    # 1. Vérification des rôles d'administration
    if any(role in admin_roles_set for role in user.roles):
        return True

    # 2. Vérification des rôles granulaires
    # Actions acceptées pour l'action demandée
    compatible_actions: Set[str] = {action, "*"}
    if action in ("delete", "create", "update"):
        compatible_actions.add("write")

    table_lower = table.lower()
    for role in user.roles:
        role_lower = role.lower()
        if ":" in role_lower:
            res, act = role_lower.split(":", 1)
            if (res == table_lower or res == "*") and act in compatible_actions:
                return True
        elif role_lower == "*" or role_lower == table_lower:
            return True

    # 3. Vérification des permissions UMA Keycloak
    # Format : [{"rsname": "users", "scopes": ["read", "write"]}]
    for perm in user.permissions:
        rsname = (perm.get("rsname") or perm.get("resource_set_name") or "").lower()
        scopes = [s.lower() for s in perm.get("scopes", [])]

        if rsname in (table_lower, "*"):
            if any(act in compatible_actions for act in scopes):
                return True

    return False
