"""Connecteur pour prestd_client.

Ce module encapsule et étend `prestd_client.PrestdClient` pour instancier
automatiquement le client avec les variables d'environnement, les valeurs par défaut
et la bonne stratégie d'authentification (Keycloak, Token statique, JWT prestd).
"""
from __future__ import annotations

from prestd_client import (
    Agg,
    BaseAuth,
    BasicAuth,
    CallableAuth,
    JWTAuth,
    KeycloakAuth,
    NoAuth,
    Op,
    PrestdAuthError,
    PrestdConnectionError,
    PrestdError,
    PrestdNotFoundError,
    PrestdPermissionError,
    PrestdServerError,
    PrestdValidationError,
    QueryBuilder,
    StaticTokenAuth,
    UserContext,
)

from .client import PrestdClient, SyncPrestdClient
from .fastapi import get_prestd_client_dependency

__all__ = [
    # Classes principales étendues
    "PrestdClient",
    "SyncPrestdClient",
    "get_prestd_client_dependency",
    # Re-exports pratiques de prestd_client
    "QueryBuilder",
    "Op",
    "Agg",
    "BaseAuth",
    "NoAuth",
    "StaticTokenAuth",
    "BasicAuth",
    "CallableAuth",
    "JWTAuth",
    "KeycloakAuth",
    "UserContext",
    "PrestdError",
    "PrestdConnectionError",
    "PrestdAuthError",
    "PrestdPermissionError",
    "PrestdNotFoundError",
    "PrestdValidationError",
    "PrestdServerError",
]

__version__ = "0.1.0"
