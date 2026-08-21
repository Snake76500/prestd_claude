"""Query builder fluide pour l'endpoint GET `/{database}/{schema}/{table}` de prestd."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from .client import PrestdClient


class QueryBuilder:
    """Construit une query string prestd puis l'exécute via un PrestdClient.

    Les instances sont créées via `PrestdClient.table(...)`. Chaque méthode
    fluide renvoie `self` — l'objet est réutilisable mais pas thread-safe.
    """

    def __init__(self, client: "PrestdClient", database: str, schema: str, table: str) -> None:
        self._client = client
        self._database = database
        self._schema = schema
        self._table = table
        self._params: dict[str, str] = {}
        self._or_conditions: list[str] = []

    # -- filtrage ------------------------------------------------------
    def filter(self, field: str, value: str) -> "QueryBuilder":
        """Ajoute un filtre brut. `value` est typiquement produit par `Op.*`."""
        self._params[field] = value
        return self

    def eq(self, field: str, value: Any) -> "QueryBuilder":
        return self.filter(field, str(value))

    def gt(self, field: str, value: Any) -> "QueryBuilder":
        return self.filter(field, f"$gt.{value}")

    def gte(self, field: str, value: Any) -> "QueryBuilder":
        return self.filter(field, f"$gte.{value}")

    def lt(self, field: str, value: Any) -> "QueryBuilder":
        return self.filter(field, f"$lt.{value}")

    def lte(self, field: str, value: Any) -> "QueryBuilder":
        return self.filter(field, f"$lte.{value}")

    def ne(self, field: str, value: Any) -> "QueryBuilder":
        return self.filter(field, f"$ne.{value}")

    def in_(self, field: str, values: Sequence[Any]) -> "QueryBuilder":
        return self.filter(field, "$in." + ",".join(str(v) for v in values))

    def nin(self, field: str, values: Sequence[Any]) -> "QueryBuilder":
        return self.filter(field, "$nin." + ",".join(str(v) for v in values))

    def is_null(self, field: str) -> "QueryBuilder":
        return self.filter(field, "$null")

    def is_not_null(self, field: str) -> "QueryBuilder":
        return self.filter(field, "$notnull")

    def like(self, field: str, pattern: str) -> "QueryBuilder":
        return self.filter(field, f"$like.{pattern}")

    def ilike(self, field: str, pattern: str) -> "QueryBuilder":
        return self.filter(field, f"$ilike.{pattern}")

    def or_(self, *conditions: str) -> "QueryBuilder":
        """Ajoute un groupe `_or`. Chaque condition est `"field=$operateur.valeur"`.

        Exemple : `.or_("title=$ilike.%foo%", "name=$ilike.%foo%")`
        """
        self._or_conditions.extend(conditions)
        return self

    # -- forme du résultat -----------------------------------------------
    def select(self, *fields: str) -> "QueryBuilder":
        self._params["_select"] = ",".join(fields)
        return self

    def order(self, *fields: str) -> "QueryBuilder":
        """Trie par un ou plusieurs champs. Préfixer par '-' pour un tri DESC."""
        self._params["_order"] = ",".join(fields)
        return self

    def group_by(self, field: str) -> "QueryBuilder":
        self._params["_groupby"] = field
        return self

    def distinct(self, value: bool = True) -> "QueryBuilder":
        self._params["_distinct"] = "true" if value else "false"
        return self

    def page(self, page: int, page_size: int | None = None) -> "QueryBuilder":
        self._params["_page"] = str(page)
        if page_size is not None:
            self._params["_page_size"] = str(page_size)
        return self

    def count(self, field: str = "*", first_only: bool = False) -> "QueryBuilder":
        self._params["_count"] = field
        if first_only:
            self._params["_count_first"] = "true"
        return self

    def renderer(self, fmt: str) -> "QueryBuilder":
        """`fmt` vaut "json" (par défaut) ou "xml"."""
        self._params["_renderer"] = fmt
        return self

    def knn_order(self, column: str, metric: str, vector: Sequence[float]) -> "QueryBuilder":
        """Tri KNN pgvector (`_korder`), nécessite prestd >= v2.4.0 + extension pgvector."""
        vec = "[" + ",".join(str(v) for v in vector) + "]"
        self._params["_korder"] = f"{column}:{metric}:{vec}"
        return self

    # -- exécution -----------------------------------------------------
    def _build_params(self) -> dict[str, str]:
        params = dict(self._params)
        if self._or_conditions:
            params["_or"] = "||".join(self._or_conditions)
        return params

    async def execute(self) -> list[dict[str, Any]]:
        """Exécute la requête SELECT et renvoie la liste des résultats.

        Exemple :
        ```python
        users = await client.table("users").eq("active", True).execute()
        ```
        """
        return await self._client._get_rows(
            self._database, self._schema, self._table, self._build_params()
        )

    async def first(self) -> dict[str, Any] | None:
        """Exécute la requête avec LIMIT 1 (page 1, taille 1) et renvoie le premier élément ou None.

        Exemple :
        ```python
        user = await client.table("users").eq("email", "alice@example.com").first()
        ```
        """
        rows = await self.page(1, 1).execute()
        return rows[0] if rows else None

    async def insert(self, data: Mapping[str, Any] | Sequence[Mapping[str, Any]]) -> Any:
        """Insère une ligne ou une liste de lignes dans la table.

        Exemples :
        ```python
        # Insertion simple
        await client.table("users").insert({"name": "Alice", "role": "admin"})

        # Insertion multiple
        await client.table("users").insert([{"name": "Bob"}, {"name": "Charlie"}])
        ```
        """
        return await self._client.insert(
            self._table,
            data,
            database=self._database,
            schema=self._schema,
        )

    async def batch_insert(self, records: Sequence[Mapping[str, Any]]) -> Any:
        """Insère une liste d'enregistrements en lot dans la table.

        Exemple :
        ```python
        await client.table("users").batch_insert([{"name": "Bob"}, {"name": "Charlie"}])
        ```
        """
        return await self._client.batch_insert(
            self._table,
            records,
            database=self._database,
            schema=self._schema,
        )

    async def update(
        self,
        data: Mapping[str, Any],
        filters: Mapping[str, str] | None = None,
        *,
        method: str = "PATCH",
    ) -> Any:
        """Met à jour les enregistrements selon les filtres chaînés (ou passés en argument).

        Exemples :
        ```python
        # Utilisation fluide avec filtre chaîné
        await client.table("users").eq("id", 42).update({"active": False})

        # Utilisation avec filtres explicites
        await client.table("users").update({"active": False}, filters={"role": "guest"})
        ```
        """
        combined_filters = dict(self._build_params())
        if filters:
            combined_filters.update(filters)
        return await self._client.update(
            self._table,
            data,
            filters=combined_filters,
            database=self._database,
            schema=self._schema,
            method=method,
        )

    async def delete(self, filters: Mapping[str, str] | None = None) -> Any:
        """Supprime les enregistrements selon les filtres chaînés (ou passés en argument).

        Exemples :
        ```python
        # Utilisation fluide avec filtre chaîné
        await client.table("users").eq("id", 42).delete()

        # Utilisation avec filtres explicites
        await client.table("users").delete(filters={"expired": "true"})
        ```
        """
        combined_filters = dict(self._build_params())
        if filters:
            combined_filters.update(filters)
        return await self._client.delete(
            self._table,
            filters=combined_filters,
            database=self._database,
            schema=self._schema,
        )
