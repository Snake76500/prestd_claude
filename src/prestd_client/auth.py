"""Middleware d'authentification pluggable pour PrestdClient.

Chaque stratégie implémente `BaseAuth` :
- `get_headers()` est appelée avant chaque requête pour obtenir les en-têtes
  à injecter (Authorization, X-Api-Key, ...).
- `on_unauthorized()` est appelée automatiquement si prestd répond 401 :
  elle peut rafraîchir l'état interne (ex: se reloguer) et, si elle renvoie
  True, la requête est retentée une fois avec les nouveaux en-têtes.

C'est la différence principale avec un `client.login(...)` appelé une seule
fois à la main : un JWT qui expire en cours de route est automatiquement
renouvelé, sans que l'appelant ait à s'en soucier.

Exemples
--------
```python
PrestdClient(url, auth=JWTAuth("prest", "prest"))         # login paresseux + re-login sur 401
PrestdClient(url, auth=StaticTokenAuth("eyJhbGciOi..."))    # token déjà généré
PrestdClient(url, auth=BasicAuth("prest", "prest"))         # HTTP Basic
PrestdClient(url, auth=CallableAuth(lambda: {"X-Api-Key": get_key()}))  # stratégie custom
```
"""
from __future__ import annotations

import asyncio
import base64
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from .exceptions import PrestdAuthError

if TYPE_CHECKING:
    from .client import PrestdClient

HeadersFactory = Callable[[], "dict[str, str] | Awaitable[dict[str, str]]"]


class BaseAuth(ABC):
    """Interface d'une stratégie d'authentification pour PrestdClient."""

    def bind(self, client: "PrestdClient") -> None:
        """Appelée automatiquement par `PrestdClient.__init__`.

        À surcharger uniquement si la stratégie a besoin d'émettre ses
        propres requêtes vers prestd (voir `JWTAuth`).
        """
        return None

    @abstractmethod
    async def get_headers(self) -> dict[str, str]:
        """En-têtes à injecter sur chaque requête sortante."""
        raise NotImplementedError

    async def on_unauthorized(self) -> bool:
        """Appelée quand une requête reçoit un 401.

        Renvoie True si l'état interne a été rafraîchi et que la requête
        doit être retentée une fois avec de nouveaux en-têtes ; False sinon
        (comportement par défaut : pas de retry).
        """
        return False


class NoAuth(BaseAuth):
    """Aucune authentification. Équivalent à ne pas passer `auth=` du tout."""

    async def get_headers(self) -> dict[str, str]:
        return {}


class StaticTokenAuth(BaseAuth):
    """Bearer token fixe, déjà généré ailleurs (pas de rafraîchissement)."""

    def __init__(self, token: str) -> None:
        self._token = token

    async def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}


class BasicAuth(BaseAuth):
    """HTTP Basic auth — les identifiants sont encodés une seule fois."""

    def __init__(self, username: str, password: str) -> None:
        creds = base64.b64encode(f"{username}:{password}".encode()).decode()
        self._header = f"Basic {creds}"

    async def get_headers(self) -> dict[str, str]:
        return {"Authorization": self._header}


class CallableAuth(BaseAuth):
    """Bascule vers une fonction (sync ou async) fournie par l'appelant.

    Utile pour une API key tournante, une signature HMAC calculée à la
    volée, un secret lu depuis HashiCorp Vault, etc. :

        auth = CallableAuth(lambda: {"X-Api-Key": vault_client.get("prest-key")})
    """

    def __init__(self, fn: HeadersFactory) -> None:
        self._fn = fn

    async def get_headers(self) -> dict[str, str]:
        result = self._fn()
        if asyncio.iscoroutine(result):
            result = await result
        return dict(result)  # type: ignore[arg-type]


class JWTAuth(BaseAuth):
    """Authentification JWT prestd (`POST /auth`).

    Se logue paresseusement au tout premier appel, met le token en cache,
    et se relogue automatiquement — une seule fois par requête — si prestd
    répond 401 (token expiré ou révoqué). Nécessite que prestd tourne avec
    `PREST_AUTH_ENABLED=true`.
    """

    def __init__(self, username: str, password: str, *, login_path: str = "/auth") -> None:
        self._username = username
        self._password = password
        self._login_path = login_path
        self._token: str | None = None
        self._client: "PrestdClient | None" = None
        self._lock: asyncio.Lock | None = None

    def bind(self, client: "PrestdClient") -> None:
        self._client = client

    async def get_headers(self) -> dict[str, str]:
        if self._token is None:
            await self._login()
        return {"Authorization": f"Bearer {self._token}"}

    async def on_unauthorized(self) -> bool:
        self._token = None
        await self._login()
        return True

    async def _login(self) -> None:
        if self._client is None:
            raise PrestdAuthError(
                "JWTAuth n'est pas attaché à un client — passez-le via "
                "PrestdClient(auth=JWTAuth(...)) plutôt que de l'utiliser seul."
            )
        # Le lock est créé au premier usage réel (dans une boucle asyncio
        # active) plutôt qu'à la construction, pour rester compatible avec
        # SyncPrestdClient qui ouvre une boucle différente à chaque appel.
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            if self._token is not None:
                return
            payload = await self._client._raw_request(
                "POST",
                self._login_path,
                json={"username": self._username, "password": self._password},
            )
            token = payload.get("token") or payload.get("access_token") if isinstance(payload, dict) else None
            if not token:
                raise PrestdAuthError(
                    "La réponse de prestd /auth ne contient pas de token", payload=payload
                )
            self._token = token
