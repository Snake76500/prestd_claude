"""prestd_client — client Python (async + sync) pour prestd (https://docs.prestd.com).

prestd expose automatiquement une API REST au-dessus d'une base PostgreSQL.
Cette librairie fournit une surcouche Pythonique typée par-dessus cette API :
query builder fluide, opérateurs de filtre, gestion des erreurs HTTP -> 
exceptions dédiées, et authentification JWT.
"""

from .auth import BaseAuth, BasicAuth, CallableAuth, JWTAuth, NoAuth, StaticTokenAuth
from .client import PrestdClient
from .exceptions import (
    PrestdAuthError,
    PrestdConnectionError,
    PrestdError,
    PrestdNotFoundError,
    PrestdServerError,
    PrestdValidationError,
)
from .operators import Agg, Op
from .query import QueryBuilder
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
    "PrestdError",
    "PrestdConnectionError",
    "PrestdAuthError",
    "PrestdNotFoundError",
    "PrestdValidationError",
    "PrestdServerError",
]

__version__ = "0.1.0"
