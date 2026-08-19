"""Middleware d'authentification et d'autorisation Keycloak pour FastAPI."""
from __future__ import annotations

import logging
import re
from typing import Callable, Iterable

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from jwt.exceptions import PyJWTError
from starlette.middleware.base import BaseHTTPMiddleware

from ..config import Settings, settings
from .keycloak import KeycloakValidator, UserContext
from .permissions import check_table_permission, resolve_action

logger = logging.getLogger("prestd_service.security.middleware")

# Regex pour extraire le nom de la table sur les routes `/tables/{table}`
TABLE_ROUTE_PATTERN = re.compile(r"^/tables/([^/?#]+)")

# Routes publiques exemptées de vérification d'authentification
DEFAULT_EXEMPT_PATHS = {
    "/healthz",
    "/readyz",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/favicon.ico",
}


class KeycloakPermissionMiddleware(BaseHTTPMiddleware):
    """Intercepte les requêtes HTTP, valide le token JWT Keycloak et vérifie les permissions sur la table ciblée."""

    def __init__(
        self,
        app,
        validator: KeycloakValidator | None = None,
        exempt_paths: Iterable[str] | None = None,
        app_settings: Settings | None = None,
    ) -> None:
        super().__init__(app)
        self.settings = app_settings or settings
        self.validator = validator or KeycloakValidator(self.settings)
        self.exempt_paths = set(exempt_paths or DEFAULT_EXEMPT_PATHS)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        # Si Keycloak auth est désactivé, on passe directement
        if not self.settings.keycloak_enabled:
            return await call_next(request)

        # Vérification des routes publiques exemptées
        path = request.url.path
        if path in self.exempt_paths or any(path.startswith(p) for p in ("/docs", "/redoc")):
            return await call_next(request)

        # Extraction de l'en-tête Authorization
        auth_header = request.headers.get("Authorization")
        if not auth_header:
            return JSONResponse(
                status_code=401,
                content={"error": "Authorization header missing. Expected 'Bearer <token>'"},
            )

        parts = auth_header.strip().split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return JSONResponse(
                status_code=401,
                content={"error": "Invalid Authorization header format. Expected 'Bearer <token>'"},
            )

        token = parts[1]

        # Décodage et validation du token JWT
        try:
            payload = self.validator.decode_token(token)
        except PyJWTError as exc:
            logger.warning(f"JWT validation failed: {exc}")
            return JSONResponse(
                status_code=401,
                content={"error": f"Invalid or expired JWT: {exc}"},
            )
        except Exception as exc:
            logger.error(f"Unexpected error validating JWT: {exc}")
            return JSONResponse(
                status_code=401,
                content={"error": "Could not validate authentication token"},
            )

        # Création du contexte utilisateur
        user = UserContext(payload)
        request.state.user = user
        request.state.jwt_claims = payload

        # Vérification des permissions si la requête cible une table
        table_match = TABLE_ROUTE_PATTERN.match(path)
        if table_match:
            table_name = table_match.group(1)
            action = resolve_action(request.method)

            has_perm = check_table_permission(
                user=user,
                table=table_name,
                action=action,
                admin_roles=self.settings.keycloak_admin_roles,
            )

            if not has_perm:
                logger.warning(
                    f"User '{user.username or user.user_id}' denied access for action '{action}' on table '{table_name}'"
                )
                return JSONResponse(
                    status_code=403,
                    content={
                        "error": f"Permission denied for action '{action}' on table '{table_name}'",
                        "table": table_name,
                        "action": action,
                    },
                )

        return await call_next(request)
