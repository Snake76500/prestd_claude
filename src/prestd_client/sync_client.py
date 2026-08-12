"""Façade synchrone au-dessus de PrestdClient, pour scripts et notebooks.

Chaque appel ouvre sa propre boucle asyncio via `asyncio.run` — pratique
pour un script ou un notebook, mais pas adapté à un service à fort débit
(dans une app FastAPI/asyncio, utilisez directement `PrestdClient`).
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from .client import PrestdClient


class SyncPrestdClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._async = PrestdClient(*args, **kwargs)

    def _run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def login(self, username: str, password: str) -> str:
        return self._run(self._async.login(username, password))

    def set_token(self, token: str) -> None:
        self._async.set_token(token)

    def health(self) -> Any:
        return self._run(self._async.health())

    def databases(self) -> list[dict[str, Any]]:
        return self._run(self._async.databases())

    def schemas(self) -> list[dict[str, Any]]:
        return self._run(self._async.schemas())

    def tables(self) -> list[dict[str, Any]]:
        return self._run(self._async.tables())

    def select(
        self,
        table: str,
        *,
        database: str | None = None,
        schema: str | None = None,
        order: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """Sélection simple : `client.select("users", active="true", role=Op.eq("admin"))`."""
        qb = self._async.table(table, database=database, schema=schema)
        for field, value in filters.items():
            qb.filter(field, str(value))
        if order:
            qb.order(order)
        if page is not None:
            qb.page(page, page_size)
        return self._run(qb.execute())

    def insert(
        self,
        table: str,
        data: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        return self._run(self._async.insert(table, data, database=database, schema=schema))

    def update(
        self,
        table: str,
        data: Mapping[str, Any],
        filters: Mapping[str, str],
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        return self._run(self._async.update(table, data, filters, database=database, schema=schema))

    def delete(
        self,
        table: str,
        filters: Mapping[str, str],
        *,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        return self._run(self._async.delete(table, filters, database=database, schema=schema))

    def close(self) -> None:
        self._run(self._async.close())

    def __enter__(self) -> "SyncPrestdClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()
