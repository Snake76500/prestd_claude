"""Façade synchrone au-dessus de PrestdClient, pour scripts et notebooks.

Chaque appel ouvre sa propre boucle asyncio via `asyncio.run` — pratique
pour un script ou un notebook, mais pas adapté à un service à fort débit
(dans une app FastAPI/asyncio, utilisez directement `PrestdClient`).
"""
from __future__ import annotations

import asyncio
from typing import Any, Mapping, Sequence

from .client import PrestdClient
from .query import QueryBuilder


class SyncPrestdClient:
    """Façade synchrone au-dessus de PrestdClient, pour scripts et notebooks.

    Exemple d'utilisation :
    ```python
    from prestd_client import SyncPrestdClient, Op

    with SyncPrestdClient("http://localhost:3000", default_database="mydb") as client:
        # Auth
        client.login("prest", "prest")

        # CRUD
        client.insert("users", {"name": "Alice", "role": "admin"})
        rows = client.select("users", role=Op.eq("admin"), order="-created_at")
        client.update("users", {"name": "Alice B."}, {"id": "1"})
        client.delete("users", {"id": "1"})
    ```
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self._async = PrestdClient(*args, **kwargs)

    def _run(self, coro: Any) -> Any:
        return asyncio.run(coro)

    def login(self, username: str, password: str) -> str:
        """POST /auth — Connexion par identifiants (si PREST_AUTH_ENABLED=true).

        Exemple :
        ```python
        token = client.login("prest", "prest")
        ```
        """
        return self._run(self._async.login(username, password))

    def set_token(self, token: str) -> None:
        """Définit manuellement le jeton Bearer JWT.

        Exemple :
        ```python
        client.set_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        ```
        """
        self._async.set_token(token)

    def health(self) -> Any:
        """GET /_health — Vérifie l'état de santé du serveur prestd.

        Exemple :
        ```python
        res = client.health()
        # -> {"status": "ok"}
        ```
        """
        return self._run(self._async.health())

    def ready(self) -> Any:
        """GET /_ready — Vérifie si prestd est prêt et connecté à PostgreSQL.

        Exemple :
        ```python
        res = client.ready()
        # -> {"status": "ok"}
        ```
        """
        return self._run(self._async.ready())

    def databases(self) -> list[dict[str, Any]]:
        """GET /databases — Liste les bases de données accessibles.

        Exemple :
        ```python
        dbs = client.databases()
        ```
        """
        return self._run(self._async.databases())

    def schemas(self) -> list[dict[str, Any]]:
        """GET /schemas — Liste les schémas disponibles.

        Exemple :
        ```python
        schemas = client.schemas()
        ```
        """
        return self._run(self._async.schemas())

    def tables(self) -> list[dict[str, Any]]:
        """GET /tables — Liste les tables accessibles.

        Exemple :
        ```python
        tables = client.tables()
        ```
        """
        return self._run(self._async.tables())

    def describe_table(
        self,
        table: str,
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /show/{database}/{schema}/{table} — Structure d'une table (colonnes, types...).

        Exemple :
        ```python
        columns = client.describe_table("users")
        ```
        """
        return self._run(
            self._async.describe_table(table, datasource=datasource, database=database, schema=schema)
        )

    def table(
        self,
        table: str,
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> SyncQueryBuilder:
        """Point d'entrée fluide synchrone pour requêter ou modifier une table.

        Exemples :
        ```python
        # SELECT
        rows = client.table("users").eq("active", True).order("-created_at").execute()

        # INSERT
        client.table("users").insert({"name": "Alice", "role": "admin"})

        # UPDATE
        client.table("users").eq("id", 42).update({"active": False})

        # DELETE
        client.table("users").eq("id", 42).delete()
        ```
        """
        async_qb = self._async.table(table, datasource=datasource, database=database, schema=schema)
        return SyncQueryBuilder(async_qb, self._run)

    def select(
        self,
        table: str,
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        order: str | None = None,
        page: int | None = None,
        page_size: int | None = None,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """GET /{database}/{schema}/{table} — Sélection simple avec filtres.

        Exemples :
        ```python
        from prestd_client import Op

        # Filtre simple et tri
        rows = client.select("users", active="true", order="-created_at")

        # Filtre avec opérateurs typés
        rows = client.select("users", age=Op.gte(18), role=Op.in_(["admin", "staff"]))

        # Pagination
        rows = client.select("users", page=1, page_size=20)
        ```
        """
        qb = self._async.table(table, datasource=datasource, database=database, schema=schema)
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
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """POST /{database}/{schema}/{table} — Insertion (dict unique ou liste de dicts).

        Exemples :
        ```python
        # Insertion unique
        client.insert("users", {"name": "Alice", "role": "admin"})

        # Insertion en lot
        client.insert("users", [{"name": "Bob"}, {"name": "Charlie"}])
        ```
        """
        return self._run(
            self._async.insert(table, data, datasource=datasource, database=database, schema=schema)
        )

    def batch_insert(
        self,
        table: str,
        records: Sequence[Mapping[str, Any]],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """POST /{database}/{schema}/{table} — Insertion en lot.

        Exemple :
        ```python
        client.batch_insert("products", [{"sku": "A1"}, {"sku": "A2"}])
        ```
        """
        return self._run(
            self._async.batch_insert(table, records, datasource=datasource, database=database, schema=schema)
        )

    def update(
        self,
        table: str,
        data: Mapping[str, Any],
        filters: Mapping[str, str],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """PATCH /{database}/{schema}/{table}?filters... — Mise à jour filtrée.

        Exemple :
        ```python
        client.update("users", {"status": "inactive"}, {"id": "42"})
        ```
        """
        return self._run(
            self._async.update(
                table, data, filters, datasource=datasource, database=database, schema=schema
            )
        )

    def delete(
        self,
        table: str,
        filters: Mapping[str, str],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """DELETE /{database}/{schema}/{table}?filters... — Suppression filtrée.

        Exemple :
        ```python
        client.delete("users", {"id": "42"})
        ```
        """
        return self._run(
            self._async.delete(table, filters, datasource=datasource, database=database, schema=schema)
        )

    def close(self) -> None:
        """Ferme la session HTTP sous-jacente."""
        self._run(self._async.close())

    def __enter__(self) -> "SyncPrestdClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()


class SyncQueryBuilder:
    """Façade synchrone pour QueryBuilder."""

    def __init__(self, async_qb: QueryBuilder, run_fn: Any) -> None:
        self._async_qb = async_qb
        self._run = run_fn

    def filter(self, field: str, value: str) -> "SyncQueryBuilder":
        self._async_qb.filter(field, value)
        return self

    def eq(self, field: str, value: Any) -> "SyncQueryBuilder":
        self._async_qb.eq(field, value)
        return self

    def gt(self, field: str, value: Any) -> "SyncQueryBuilder":
        self._async_qb.gt(field, value)
        return self

    def gte(self, field: str, value: Any) -> "SyncQueryBuilder":
        self._async_qb.gte(field, value)
        return self

    def lt(self, field: str, value: Any) -> "SyncQueryBuilder":
        self._async_qb.lt(field, value)
        return self

    def lte(self, field: str, value: Any) -> "SyncQueryBuilder":
        self._async_qb.lte(field, value)
        return self

    def ne(self, field: str, value: Any) -> "SyncQueryBuilder":
        self._async_qb.ne(field, value)
        return self

    def in_(self, field: str, values: Sequence[Any]) -> "SyncQueryBuilder":
        self._async_qb.in_(field, values)
        return self

    def nin(self, field: str, values: Sequence[Any]) -> "SyncQueryBuilder":
        self._async_qb.nin(field, values)
        return self

    def is_null(self, field: str) -> "SyncQueryBuilder":
        self._async_qb.is_null(field)
        return self

    def is_not_null(self, field: str) -> "SyncQueryBuilder":
        self._async_qb.is_not_null(field)
        return self

    def like(self, field: str, pattern: str) -> "SyncQueryBuilder":
        self._async_qb.like(field, pattern)
        return self

    def ilike(self, field: str, pattern: str) -> "SyncQueryBuilder":
        self._async_qb.ilike(field, pattern)
        return self

    def or_(self, *conditions: str) -> "SyncQueryBuilder":
        self._async_qb.or_(*conditions)
        return self

    def select(self, *fields: str) -> "SyncQueryBuilder":
        self._async_qb.select(*fields)
        return self

    def order(self, *fields: str) -> "SyncQueryBuilder":
        self._async_qb.order(*fields)
        return self

    def group_by(self, field: str) -> "SyncQueryBuilder":
        self._async_qb.group_by(field)
        return self

    def distinct(self, value: bool = True) -> "SyncQueryBuilder":
        self._async_qb.distinct(value)
        return self

    def page(self, page: int, page_size: int | None = None) -> "SyncQueryBuilder":
        self._async_qb.page(page, page_size)
        return self

    def count(self, field: str = "*", first_only: bool = False) -> "SyncQueryBuilder":
        self._async_qb.count(field, first_only=first_only)
        return self

    def renderer(self, fmt: str) -> "SyncQueryBuilder":
        self._async_qb.renderer(fmt)
        return self

    def knn_order(self, column: str, metric: str, vector: Sequence[float]) -> "SyncQueryBuilder":
        self._async_qb.knn_order(column, metric, vector)
        return self

    def execute(self) -> list[dict[str, Any]]:
        """Exécute le SELECT de manière synchrone."""
        return self._run(self._async_qb.execute())

    def first(self) -> dict[str, Any] | None:
        """Récupère le premier enregistrement."""
        return self._run(self._async_qb.first())

    def insert(self, data: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Any:
        """Insère des données dans la table."""
        return self._run(self._async_qb.insert(data))

    def batch_insert(self, records: Sequence[Mapping[str, Any]]) -> Any:
        """Insère un lot d'enregistrements."""
        return self._run(self._async_qb.batch_insert(records))

    def update(
        self,
        data: Mapping[str, Any],
        filters: Mapping[str, str] | None = None,
        *,
        method: str = "PATCH",
    ) -> Any:
        """Met à jour les lignes filtrées."""
        return self._run(self._async_qb.update(data, filters=filters, method=method))

    def delete(self, filters: Mapping[str, str] | None = None) -> Any:
        """Supprime les lignes filtrées."""
        return self._run(self._async_qb.delete(filters=filters))
