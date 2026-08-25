"""prestd_client — client Python (async + sync) pour prestd (https://docs.prestd.com).

prestd expose automatiquement une API REST au-dessus d'une base PostgreSQL.
Cette librairie fournit une surcouche Pythonique typée par-dessus cette API :
query builder fluide, opérateurs de filtre, gestion des erreurs HTTP -> 
exceptions dédiées, et authentification JWT.
"""

from .auth import (
    BaseAuth,
    BasicAuth,
    CallableAuth,
    JWTAuth,
    KeycloakAuth,
    NoAuth,
    StaticTokenAuth,
)
from .client import PrestdClient
from .exceptions import (
    PrestdAuthError,
    PrestdConnectionError,
    PrestdError,
    PrestdNotFoundError,
    PrestdPermissionError,
    PrestdServerError,
    PrestdValidationError,
)
from .operators import Agg, Op
from .query import QueryBuilder
from .security import UserContext
from .sync_client import SyncPrestdClient

__all__ = [
    "PrestdClient",
    "SyncPrestdClient",
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
