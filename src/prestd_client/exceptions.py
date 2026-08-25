"""Exceptions du client prestd_client."""
from __future__ import annotations

from typing import Any


class PrestdError(Exception):
    """Classe de base pour toutes les erreurs levées par prestd_client."""

    def __init__(self, message: str, *, status_code: int | None = None, payload: Any = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.payload = payload

    def __str__(self) -> str:  # pragma: no cover - cosmétique
        if self.status_code is not None:
            return f"[{self.status_code}] {self.message}"
        return self.message


class PrestdConnectionError(PrestdError):
    """prestd est injoignable (réseau, DNS, timeout)."""


class PrestdAuthError(PrestdError):
    """Réponse 401 (non authentifié) ou échec du login JWT (POST /auth)."""


class PrestdPermissionError(PrestdAuthError):
    """Réponse 403 (droits / permissions insuffisants sur la ressource)."""


class PrestdNotFoundError(PrestdError):
    """Réponse 404 (database/schema/table/row inconnue)."""


class PrestdValidationError(PrestdError):
    """Réponse 400 (filtre invalide, identifiant invalide, corps JSON malformé)."""


class PrestdServerError(PrestdError):
    """Réponse 5xx côté prestd."""


def raise_for_status(status_code: int, message: str, payload: Any = None) -> None:
    """Traduit un code HTTP renvoyé par prestd en l'exception adéquate."""
    if status_code < 400:
        return
    if status_code == 401:
        raise PrestdAuthError(message, status_code=status_code, payload=payload)
    if status_code == 403:
        raise PrestdPermissionError(message, status_code=status_code, payload=payload)
    if status_code == 404:
        raise PrestdNotFoundError(message, status_code=status_code, payload=payload)
    if status_code == 400:
        raise PrestdValidationError(message, status_code=status_code, payload=payload)
    if status_code >= 500:
        raise PrestdServerError(message, status_code=status_code, payload=payload)
    raise PrestdError(message, status_code=status_code, payload=payload)
