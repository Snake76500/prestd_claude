"""Client HTTP asynchrone pour prestd (https://docs.prestd.com).

Couvre les endpoints documentés dans l'API Reference officielle :
- GET  /_health, /_ready
- GET  /databases, /schemas, /tables, /show/{db}/{schema}/{table}
- GET  /{db}/{schema}/{table}      (SELECT, filtres, pagination, tri...)
- POST /{db}/{schema}/{table}      (INSERT, y compris en lot)
- PATCH|PUT /{db}/{schema}/{table} (UPDATE filtré par query string)
- DELETE    /{db}/{schema}/{table} (DELETE filtré par query string)
- POST /auth                       (login JWT, si PREST_AUTH_ENABLED=true)
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Sequence

import httpx

from .auth import BaseAuth, KeycloakAuth
from .exceptions import (
    PrestdAuthError,
    PrestdConnectionError,
    PrestdPermissionError,
    raise_for_status,
)
from .query import QueryBuilder
from .security import (
    UserContext,
    check_table_permission,
    decode_jwt_payload_unverified,
    resolve_action,
)

logger = logging.getLogger("prestd_client")

DEFAULT_TIMEOUT = 30.0


class PrestdClient:
    """Wrapper asynchrone léger autour d'un serveur prestd.

    Exemple — authentification via middleware (recommandé, re-login auto sur 401)
    --------------------------------------------------------------------------
    ```python
    from prestd_client import PrestdClient, JWTAuth

    async with PrestdClient(
        "http://localhost:3000", default_database="mydb", auth=JWTAuth("prest", "prest")
    ) as client:
        rows = await client.table("users").eq("active", True).order("-created_at").execute()
    ```

    Exemple — authentification manuelle (toujours supportée)
    ----------------------------------------------------------
    ```python
    async with PrestdClient("http://localhost:3000", default_database="mydb") as client:
        await client.login("prest", "prest")  # si PREST_AUTH_ENABLED=true
        rows = await client.table("users").execute()
    ```
    """

    def __init__(
        self,
        base_url: str,
        *,
        default_database: str | None = None,
        default_schema: str = "public",
        timeout: float = DEFAULT_TIMEOUT,
        verify: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
        auth: BaseAuth | None = None,
        keycloak_token: str | None = None,
        verify_permissions: bool = True,
        admin_roles: Sequence[str] | None = None,
        default_page_size: int | None = None,
        max_page_size: int | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.default_database = default_database
        self.default_schema = default_schema
        self.default_page_size = default_page_size
        self.max_page_size = max_page_size
        self._token: str | None = None
        self._keycloak_token: str | None = keycloak_token
        self.verify_permissions = verify_permissions
        self.admin_roles = list(admin_roles) if admin_roles else None
        self._auth = auth
        if self._keycloak_token and self._auth is None:
            self._auth = KeycloakAuth(self._keycloak_token)
        if self._auth is not None:
            self._auth.bind(self)
        self._http = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            verify=verify,
            transport=transport,
        )

    # -- cycle de vie ----------------------------------------------------
    async def __aenter__(self) -> "PrestdClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def close(self) -> None:
        await self._http.aclose()

    def set_token(self, token: str) -> None:
        """Attache manuellement un JWT déjà généré (évite un aller-retour /auth).

        Un token posé ici a priorité sur le middleware `auth=...` éventuellement
        configuré — utile pour un override ponctuel.

        Exemple :
        ```python
        client.set_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")
        ```
        """
        self._token = token

    def set_keycloak_token(self, token: str) -> None:
        """Attache un token JWT Keycloak pour authentifier les requêtes et vérifier les droits."""
        self._keycloak_token = token
        self._auth = KeycloakAuth(token)
        self._auth.bind(self)

    @property
    def current_user(self) -> UserContext | None:
        """Retourne le UserContext (identifiant, username, rôles) extrait du token Keycloak actif."""
        token = self._keycloak_token
        if not token and isinstance(self._auth, KeycloakAuth):
            token = self._auth.token
        if not token and self._token:
            token = self._token
        if token:
            payload = decode_jwt_payload_unverified(token)
            if payload:
                return UserContext(payload)
        return None

    def has_table_permission(self, table: str, action: str) -> bool:
        """Vérifie si l'utilisateur courant possède le droit (`read`, `write`, `delete`) sur `table`."""
        user = self.current_user
        if not user:
            return False
        return check_table_permission(user, table, action, admin_roles=self.admin_roles)

    # -- authentification --------------------------------------------------
    async def login(self, username: str, password: str) -> str:
        """POST /auth — fonctionne uniquement si prestd tourne avec PREST_AUTH_ENABLED=true.

        Toujours disponible pour un login explicite ponctuel. Pour un
        renouvellement automatique du token en cas d'expiration (401), passez
        plutôt `auth=JWTAuth(username, password)` au constructeur.

        Exemple :
        ```python
        token = await client.login("prest", "prest")
        # -> "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
        ```
        """
        resp = await self._raw_request(
            "POST", "/auth", json={"username": username, "password": password}
        )
        token = None
        if isinstance(resp, dict):
            token = resp.get("token") or resp.get("access_token")
        if not token:
            raise PrestdAuthError("La réponse de prestd /auth ne contient pas de token", payload=resp)
        self._token = token
        return token

    # -- découverte du schéma ---------------------------------------------
    async def health(self) -> Any:
        """GET /_health — Vérifie la santé basique du serveur prestd.

        Exemple :
        ```python
        status = await client.health()
        # -> {"status": "ok"}
        ```
        """
        return await self._request("GET", "/_health")

    async def ready(self) -> Any:
        """GET /_ready — Vérifie si prestd est prêt (connexion base de données active).

        Exemple :
        ```python
        readiness = await client.ready()
        # -> {"status": "ok"}
        ```
        """
        return await self._request("GET", "/_ready")

    async def databases(self) -> list[dict[str, Any]]:
        """GET /databases — Liste toutes les bases de données accessibles.

        Exemple :
        ```python
        dbs = await client.databases()
        # -> [{"datname": "postgres"}, {"datname": "prest"}]
        ```
        """
        return await self._request("GET", "/databases")

    async def schemas(self) -> list[dict[str, Any]]:
        """GET /schemas — Liste tous les schémas disponibles.

        Exemple :
        ```python
        schemas = await client.schemas()
        # -> [{"schema_name": "public"}, {"schema_name": "auth"}]
        ```
        """
        return await self._request("GET", "/schemas")

    async def tables(self) -> list[dict[str, Any]]:
        """GET /tables — Liste toutes les tables accessibles.

        Exemple :
        ```python
        tables = await client.tables()
        # -> [{"table_name": "users"}, {"table_name": "orders"}]
        ```
        """
        return await self._request("GET", "/tables")

    async def describe_table(
        self,
        table: str,
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /show/{database}/{schema}/{table} — Structure de la table (colonnes, types...).

        Exemples :
        ```python
        # Utilise la base/datasource par défaut configurée sur le client
        columns = await client.describe_table("users")

        # Avec schéma et base explicites
        columns = await client.describe_table(
            "users", database="mydb", schema="public"
        )
        # -> [{"column_name": "id", "data_type": "integer"}, {"column_name": "name", "data_type": "text"}]
        ```
        """
        db, sch = self._resolve(database=database, schema=schema, datasource=datasource)
        return await self._request("GET", f"/show/{db}/{sch}/{table}")

    # -- CRUD ----------------------------------------------------------------
    def table(
        self,
        table: str,
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> QueryBuilder:
        """Point d'entrée fluide pour requêter ou modifier une table (SELECT, INSERT, UPDATE, DELETE).

        Exemples :
        ```python
        # 1. SELECT avec filtres et tri
        rows = await (
            client.table("users")
            .eq("active", True)
            .gt("age", 18)
            .order("-created_at")
            .page(1, 10)
            .execute()
        )

        # Récupérer un seul enregistrement
        user = await client.table("users").eq("email", "john@example.com").first()

        # 2. INSERT via table() (le paramètre table n'a pas besoin d'être répété)
        await client.table("users").insert({"name": "Alice", "role": "admin"})
        await client.table("users").batch_insert([{"name": "Bob"}, {"name": "Charlie"}])

        # 3. UPDATE via table() avec filtres chaînés
        await client.table("users").eq("id", 42).update({"active": False})

        # 4. DELETE via table() avec filtres chaînés
        await client.table("users").eq("id", 42).delete()
        ```
        """
        db, sch = self._resolve(database=database, schema=schema, datasource=datasource)
        return QueryBuilder(self, db, sch, table)

    async def insert(
        self,
        table: str,
        data: Mapping[str, Any] | Sequence[Mapping[str, Any]],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """POST /{database}/{schema}/{table} — Insertion directe d'un ou plusieurs enregistrements.

        `table` est le nom de la table cible (obligatoire en appel direct).
        `data` peut être un dictionnaire unique (1 ligne) ou une liste de dictionnaires (lot).

        Exemples :
        ```python
        # Insertion d'une seule ligne (nécessite le nom de la table en 1er argument)
        new_user = await client.insert("users", {
            "name": "Alice",
            "email": "alice@example.com",
            "active": True,
        })

        # Insertion multiple en une seule requête
        new_users = await client.insert("users", [
            {"name": "Bob", "email": "bob@example.com"},
            {"name": "Charlie", "email": "charlie@example.com"},
        ])

        # En spécifiant la base/schéma explicitement
        await client.insert(
            "logs",
            {"event": "login", "user_id": 42},
            database="mydb",
            schema="audit",
        )

        # Alternative fluide équivalente via table("users") :
        await client.table("users").insert({"name": "Alice", "active": True})
        await client.table("users").batch_insert([{"name": "Bob"}, {"name": "Charlie"}])
        ```
        """
        db, sch = self._resolve(database=database, schema=schema, datasource=datasource)
        return await self._request("POST", f"/{db}/{sch}/{table}", json=data)

    async def update(
        self,
        table: str,
        data: Mapping[str, Any],
        filters: Mapping[str, str],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        method: str = "PATCH",
    ) -> Any:
        """PATCH/PUT /{database}/{schema}/{table}?filters... — Mise à jour filtrée.

        `filters` est un dictionnaire `{champ: valeur_ou_opérateur}` obligatoire
        pour éviter une mise à jour accidentelle de toute la table.

        Exemples :
        ```python
        # Mise à jour par ID simple (PATCH par défaut)
        updated = await client.update(
            "users",
            data={"active": False, "role": "guest"},
            filters={"id": "42"},
        )

        # Mise à jour avec opérateur de filtre prestd
        from prestd_client import Op
        await client.update(
            "orders",
            data={"status": "archived"},
            filters={"created_at": Op.lt("2024-01-01")},
        )

        # Remplacement complet via PUT
        await client.update(
            "profiles",
            data={"bio": "Nouvelle bio", "website": "https://example.com"},
            filters={"user_id": "10"},
            method="PUT",
        )
        ```
        """
        if not filters:
            raise ValueError(
                "update() nécessite au moins un filtre — prestd exécute sinon un "
                "UPDATE inconditionnel sur toutes les lignes de la table."
            )
        db, sch = self._resolve(database=database, schema=schema, datasource=datasource)
        return await self._request(method, f"/{db}/{sch}/{table}", params=dict(filters), json=data)

    async def delete(
        self,
        table: str,
        filters: Mapping[str, str],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """DELETE /{database}/{schema}/{table}?filters... — Suppression filtrée.

        `filters` est un dictionnaire `{champ: valeur_ou_opérateur}` obligatoire
        pour éviter une suppression inconditionnelle de toute la table.

        Exemples :
        ```python
        # Suppression par ID
        await client.delete("users", filters={"id": "42"})

        # Suppression par condition avec opérateur
        from prestd_client import Op
        await client.delete("sessions", filters={"expired_at": Op.lt("2026-01-01")})

        # Suppression avec plusieurs filtres combinés
        await client.delete(
            "cart_items",
            filters={"user_id": "123", "status": "abandoned"},
            database="shop_db",
            schema="public",
        )
        ```
        """
        if not filters:
            raise ValueError(
                "delete() nécessite au moins un filtre — prestd exécute sinon un "
                "DELETE inconditionnel sur toutes les lignes de la table."
            )
        db, sch = self._resolve(database=database, schema=schema, datasource=datasource)
        return await self._request("DELETE", f"/{db}/{sch}/{table}", params=dict(filters))

    async def batch_insert(
        self,
        table: str,
        records: Sequence[Mapping[str, Any]],
        *,
        datasource: str | None = None,
        database: str | None = None,
        schema: str | None = None,
    ) -> Any:
        """POST /{database}/{schema}/{table} — Insertion en lot (sucre syntaxique pour `insert`).

        Exemples :
        ```python
        items = [
            {"sku": "A001", "name": "Clavier", "price": 49.99},
            {"sku": "A002", "name": "Souris", "price": 29.99},
            {"sku": "A003", "name": "Écran", "price": 199.99},
        ]
        result = await client.batch_insert("products", items)
        ```
        """
        return await self.insert(table, list(records), datasource=datasource, database=database, schema=schema)

    # -- interne ---------------------------------------------------------------
    async def _get_rows(
        self, database: str, schema: str, table: str, params: dict[str, str]
    ) -> list[dict[str, Any]]:
        result = await self._request("GET", f"/{database}/{schema}/{table}", params=params)
        if isinstance(result, list):
            return result
        return [result] if result else []

    def _resolve(
        self,
        database: str | None = None,
        schema: str | None = None,
        datasource: str | None = None,
    ) -> tuple[str, str]:
        db = datasource or database or self.default_database
        if not db:
            raise ValueError(
                "Aucune database ou datasource fournie et aucun default_database configuré sur PrestdClient."
            )
        sch = schema or self.default_schema
        return db, sch

    async def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Requête authentifiée :
        1. Vérifie préventivement les permissions Keycloak (si verify_permissions=True).
        2. Injecte les en-têtes d'authentification.
        3. Gère le retry automatique sur 401 via `auth.on_unauthorized()`.
        """
        # Vérification préventive des permissions Keycloak côté SDK
        if self.verify_permissions:
            user = self.current_user
            if user is not None:
                table = self._extract_table_from_path(path)
                if table:
                    action = resolve_action(method)
                    if not check_table_permission(user, table, action, admin_roles=self.admin_roles):
                        raise PrestdPermissionError(
                            f"Permission denied for action '{action}' on table '{table}'",
                            status_code=403,
                            payload={
                                "error": f"Permission denied for action '{action}' on table '{table}'",
                                "table": table,
                                "action": action,
                                "user": user.username or user.user_id,
                            },
                        )

        headers = dict(kwargs.pop("headers", {}) or {})
        if self._token:
            headers.setdefault("Authorization", f"Bearer {self._token}")
        elif self._auth is not None:
            headers.update(await self._auth.get_headers())

        resp = await self._send(method, path, headers=headers, **kwargs)

        if (
            resp.status_code == 401
            and not self._token
            and self._auth is not None
            and await self._auth.on_unauthorized()
        ):
            headers.update(await self._auth.get_headers())
            resp = await self._send(method, path, headers=headers, **kwargs)

        return self._parse_response(resp)

    def _extract_table_from_path(self, path: str) -> str | None:
        """Extrait le nom de la table cible depuis le chemin d'URL prestd /{db}/{schema}/{table}."""
        if path.startswith("/show/") or path in (
            "/_health",
            "/_ready",
            "/databases",
            "/schemas",
            "/tables",
            "/auth",
        ):
            return None
        parts = [p for p in path.strip("/").split("/") if p]
        if len(parts) >= 3:
            return parts[2]
        return None

    async def _raw_request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Requête sans injection d'auth ni retry sur 401.

        Utilisée par les stratégies d'auth elles-mêmes (ex: `JWTAuth`) et par
        `login()`, pour éviter toute récursion ou double authentification.
        """
        resp = await self._send(method, path, **kwargs)
        return self._parse_response(resp)

    async def _send(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise PrestdConnectionError(f"Timeout en appelant prestd {method} {path}") from exc
        except httpx.TransportError as exc:
            raise PrestdConnectionError(
                f"Impossible de joindre prestd à {self.base_url}{path}: {exc}"
            ) from exc

    def _parse_response(self, resp: httpx.Response) -> Any:
        if resp.status_code >= 400:
            try:
                payload = resp.json()
                message = payload.get("error") or payload.get("message") or resp.text
            except Exception:
                payload, message = None, resp.text
            raise_for_status(resp.status_code, message, payload)

        if resp.status_code == 204 or not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return resp.text
