# prestd-client

Librairie Python (client async + wrapper microservice FastAPI) pour piloter
[prestd](https://docs.prestd.com) — le serveur qui expose automatiquement une
API REST au-dessus d'une base PostgreSQL.

## Pourquoi ce projet

prestd génère déjà une API REST complète à partir de votre schéma Postgres,
mais côté Python on manipule directement `httpx` + des query strings à la
main. Ce projet ajoute une couche Pythonique par-dessus :

1. **`prestd_client`** — librairie client async (+ façade sync) : query
   builder fluide, opérateurs de filtre typés, exceptions dédiées, JWT.
2. **`service/`** — microservice FastAPI qui expose cette librairie derrière
   sa propre API : auth par clé API indépendante, erreurs JSON structurées,
   `/healthz` / `/readyz`, et un point d'extension unique pour brancher plus
   tard du rate limiting, du cache ou de la logique métier — sans exposer
   prestd directement sur le réseau.

```
┌──────────────┐      ┌────────────────────┐      ┌────────────┐      ┌────────────┐
│  Vos clients │─────▶│  microservice       │─────▶│   prestd   │─────▶│ PostgreSQL │
│ (HTTP + API  │      │  FastAPI (ce repo)  │      │  (Go, REST)│      │            │
│  key propre) │      │  routers/*.py       │      │            │      │            │
└──────────────┘      └────────────────────┘      └────────────┘      └────────────┘
                              │
                              └── ou utilisez src/prestd_client directement
                                  dans vos propres scripts/services Python
```

## Structure du projet

```
prestd-microservice/
├── pyproject.toml
├── src/prestd_client/       # la librairie, installable seule (pip install .)
│   ├── client.py            # PrestdClient (async)
│   ├── sync_client.py       # SyncPrestdClient (façade synchrone)
│   ├── query.py             # QueryBuilder fluide
│   ├── operators.py         # Op.* (filtres) et Agg.* (agrégations)
│   └── exceptions.py
├── service/                 # le microservice FastAPI (installable via extra "service")
│   ├── main.py
│   ├── config.py            # variables d'environnement (pydantic-settings)
│   ├── dependencies.py
│   └── routers/{health,meta,records}.py
├── docker/
│   ├── Dockerfile
│   └── docker-compose.yml   # Postgres + prestd + microservice, prêt à l'emploi
└── tests/                   # pytest + respx (mock HTTP, aucun serveur requis)
```

## Installation

```bash
# la librairie seule
pip install -e .

# librairie + microservice
pip install -e ".[service]"

# + dépendances de test
pip install -e ".[dev]"
```

## Utiliser la librairie directement

```python
import asyncio
from prestd_client import PrestdClient, Op

async def main():
    async with PrestdClient("http://localhost:3000", default_database="mydb") as client:
        # authentification JWT si PREST_AUTH_ENABLED=true côté prestd
        await client.login("prest", "prest")

        # SELECT avec filtres, tri, pagination
        rows = await (
            client.table("users")
            .eq("active", True)
            .gt("age", Op.eq(18))  # ou directement .gt("age", 18)
            .order("-created_at")
            .page(1, 20)
            .execute()
        )

        # INSERT (un dict, ou une liste pour un insert en lot)
        await client.insert("users", {"name": "Fabien", "active": True})
        await client.batch_insert("users", [{"name": "Reynald"}, {"name": "Ragnar"}])

        # UPDATE / DELETE — filtres obligatoires (garde-fou contre un
        # UPDATE/DELETE inconditionnel sur toute la table)
        await client.update("users", {"active": False}, {"id": "42"})
        await client.delete("users", {"id": "42"})

asyncio.run(main())
```

### Filtres disponibles (`Op`, ou méthodes directes sur `QueryBuilder`)

| Opérateur prestd | `Op.*`                    | `QueryBuilder.*`         |
|---|---|---|
| égalité          | `Op.eq(v)`                 | `.eq(field, v)`          |
| `$gt` / `$gte`    | `Op.gt(v)` / `Op.gte(v)`   | `.gt()` / `.gte()`       |
| `$lt` / `$lte`    | `Op.lt(v)` / `Op.lte(v)`   | `.lt()` / `.lte()`       |
| `$ne`             | `Op.ne(v)`                 | `.ne()`                  |
| `$in` / `$nin`    | `Op.in_([...])`            | `.in_()` / `.nin()`      |
| `$null` / `$notnull` | `Op.is_null()`          | `.is_null()` / `.is_not_null()` |
| `$true`/`$nottrue`/`$false`/`$notfalse` | `Op.is_true()` ... | — |
| `$like` / `$ilike` (+ négations) | `Op.like(p)` ... | `.like()` / `.ilike()` |
| ltree (`$ltreelanc`, ...) | `Op.ltree_ancestor(p)` ... | — |

Et côté forme du résultat : `.select(*fields)`, `.order(*fields)` (préfixe
`-` pour DESC), `.group_by(field)`, `.distinct()`, `.page(n, size)`,
`.count(field, first_only=...)`, `.or_(*conditions)`, `.knn_order(...)`
(recherche vectorielle pgvector, prestd ≥ v2.4.0).

Référence complète des paramètres : https://docs.prestd.com/api-reference/parameters

### Authentification (middleware pluggable)

L'authentification vers prestd se configure via un objet `auth=` passé au
constructeur — c'est un middleware appliqué à chaque requête, avec un hook
de rafraîchissement automatique en cas de 401 :

```python
from prestd_client import PrestdClient, JWTAuth, StaticTokenAuth, BasicAuth, CallableAuth

# JWT prestd : login paresseux au premier appel, re-login automatique si le
# token expire (401) — sans redémarrer le client ni relancer login() à la main
client = PrestdClient(url, default_database="mydb", auth=JWTAuth("prest", "prest"))

# Token déjà généré ailleurs
client = PrestdClient(url, default_database="mydb", auth=StaticTokenAuth("eyJhbGciOi..."))

# HTTP Basic
client = PrestdClient(url, default_database="mydb", auth=BasicAuth("prest", "prest"))

# Stratégie sur mesure : API key tournante, secret HashiCorp Vault, HMAC...
client = PrestdClient(url, default_database="mydb",
                       auth=CallableAuth(lambda: {"X-Api-Key": vault_client.get("prest-key")}))
```

Écrire sa propre stratégie revient à sous-classer `BaseAuth` :

```python
from prestd_client.auth import BaseAuth

class MyAuth(BaseAuth):
    async def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {await get_token_from_somewhere()}"}

    async def on_unauthorized(self) -> bool:
        await refresh_token_somehow()
        return True  # retente la requête une fois avec le nouveau token
```

`client.login(username, password)` et `client.set_token(token)` restent
disponibles pour un login/override ponctuel — un token posé via `set_token`
prend toujours le pas sur le middleware `auth=...`.

> `SyncPrestdClient` + `JWTAuth` : chaque appel synchrone ouvre sa propre
> boucle asyncio (`asyncio.run`). Le cache de token fonctionne normalement,
> mais pour un usage soutenu avec re-login fréquent sur 401, préférez
> `PrestdClient` async directement (FastAPI, Airflow, etc.).

### Exemples détaillés par endpoint

#### 1. Santé et état du serveur (Health & Readiness)

```python
# GET /_health — Vérifie que le serveur prestd répond
health = await client.health()
# -> {"status": "ok"}

# GET /_ready — Vérifie que la connexion PostgreSQL sous-jacente est active
ready = await client.ready()
# -> {"status": "ok"}
```

#### 2. Découverte de schéma et métadonnées

```python
# GET /databases — Liste les bases accessibles
dbs = await client.databases()

# GET /schemas — Liste les schémas
schemas = await client.schemas()

# GET /tables — Liste les tables de la base
tables = await client.tables()

# GET /show/{db}/{schema}/{table} — Structure détaillée d'une table (colonnes, types)
columns = await client.describe_table("users")
# Ou avec datasource / base / schéma explicites :
columns = await client.describe_table("users", datasource="analytics_db", schema="public")
```

#### 3. Lecture et requêtes (SELECT)

```python
# GET /{db}/{schema}/{table} avec filtres, tri, pagination
users = await (
    client.table("users")
    .eq("active", True)
    .gte("age", 18)
    .in_("role", ["admin", "editor"])
    .order("-created_at")
    .page(1, 20)
    .execute()
)

# Récupérer un enregistrement unique
user = await client.table("users").eq("id", "42").first()

# Projection de colonnes spécifiques (_select)
cols = await client.table("users").select("id", "name", "email").execute()

# Comptage d'enregistrements (_count)
total = await client.table("users").count().execute()

# Recherche vectorielle pgvector (_korder, prestd >= v2.4.0)
matches = await (
    client.table("documents")
    .knn_order("embedding", "<=>", [0.12, 0.45, -0.67])
    .page(1, 5)
    .execute()
)
```

#### 4. Insertion simple et par lot (INSERT)

Deux syntaxes équivalentes sont disponibles :

```python
# A. Syntaxe fluide via table() (recommandée)
new_user = await client.table("users").insert({
    "name": "Alice Dupont",
    "email": "alice@example.com",
    "role": "admin",
    "active": True,
})
new_users = await client.table("users").batch_insert([
    {"name": "Bob", "email": "bob@example.com"},
    {"name": "Charlie", "email": "charlie@example.com"},
])

# B. Syntaxe directe sur le client (le nom de la table est le 1er argument obligatoire)
new_user = await client.insert("users", {
    "name": "Alice Dupont",
    "email": "alice@example.com",
    "role": "admin",
    "active": True,
})
new_users = await client.batch_insert("users", [
    {"name": "Bob", "email": "bob@example.com"},
    {"name": "Charlie", "email": "charlie@example.com"},
])

# Spécifier base / schéma pour l'insertion
await client.insert(
    "audit_logs",
    {"action": "login", "user_id": 42},
    database="logs_db",
    schema="audit",
)
```

#### 5. Mise à jour (UPDATE)

```python
# A. Syntaxe fluide via table() avec filtres chaînés
await client.table("users").eq("id", 42).update({"active": False, "role": "disabled"})

# B. Syntaxe directe sur le client (table en 1er argument, filtres obligatoires)
updated = await client.update(
    "users",
    data={"active": False, "role": "disabled"},
    filters={"id": "42"},
)

# Mise à jour avec opérateur de filtre Op.*
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

#### 6. Suppression (DELETE)

```python
# A. Syntaxe fluide via table() avec filtres chaînés
await client.table("users").eq("id", 42).delete()

# B. Syntaxe directe sur le client (table en 1er argument, filtres obligatoires)
deleted = await client.delete(
    "users",
    filters={"id": "42"},
)

# Suppression conditionnelle avec filtres multiples ou opérateurs
await client.delete(
    "sessions",
    filters={"expired_at": Op.lt("2026-01-01"), "revoked": "true"},
)
```

#### 7. Authentification (POST /auth & Bearer Token)

```python
# Login explicite ponctuel (si PREST_AUTH_ENABLED=true)
token = await client.login("prest", "prest")

# Poser manuellement un token existant
client.set_token("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...")

# Recommandé : Middleware avec auto-refresh sur 401
client = PrestdClient(
    "http://localhost:3000",
    default_database="mydb",
    auth=JWTAuth("prest", "prest"),
)
```

### Façade synchrone (scripts, notebooks)

```python
from prestd_client import SyncPrestdClient, Op

with SyncPrestdClient("http://localhost:3000", default_database="mydb") as client:
    # Authentification
    client.login("prest", "prest")

    # Santé & Métadonnées
    print("Health:", client.health())
    print("Tables:", client.tables())

    # INSERT & BATCH INSERT
    client.insert("users", {"name": "Alice", "role": "admin"})
    client.batch_insert("users", [{"name": "Bob"}, {"name": "Charlie"}])

    # SELECT
    rows = client.select("users", active="true", role=Op.eq("admin"), order="-created_at", page=1, page_size=10)

    # UPDATE
    client.update("users", {"active": "false"}, {"id": "1"})

    # DELETE
    client.delete("users", {"id": "1"})
```

⚠️ `SyncPrestdClient` ouvre une boucle asyncio à chaque appel (`asyncio.run`) :
pratique pour un script, à éviter dans un service à fort débit — utilisez
`PrestdClient` directement dans ce cas (FastAPI, Airflow, etc.).

## Le microservice

```bash
cp .env.example .env   # à adapter
uvicorn service.main:app --reload
```

Endpoints exposés :

| Méthode | Route | Description |
|---|---|---|
| GET | `/healthz` | liveness du microservice |
| GET | `/readyz` | + ping de prestd en amont |
| GET | `/meta/databases`, `/meta/schemas`, `/meta/tables` | découverte de schéma |
| GET | `/meta/tables/{table}` | structure d'une table (base par défaut) |
| GET | `/meta/datasource/{datasource}/tables/{table}` | structure d'une table pour un datasource spécifique |
| GET | `/tables/{table}?...` | liste/filtre (base par défaut) |
| POST | `/tables/{table}` | insertion (base par défaut) |
| PATCH | `/tables/{table}?id=...` | mise à jour filtrée (base par défaut) |
| DELETE | `/tables/{table}?id=...` | suppression filtrée (base par défaut) |
| GET | `/datasource/{datasource}/{table}?...` | liste/filtre pour un datasource spécifique |
| POST | `/datasource/{datasource}/{table}` | insertion pour un datasource spécifique |
| PATCH | `/datasource/{datasource}/{table}?id=...` | mise à jour filtrée pour un datasource spécifique |
| DELETE | `/datasource/{datasource}/{table}?id=...` | suppression filtrée pour un datasource spécifique |

Si `SERVICE_API_KEY` est définie dans l'environnement, toutes les routes
`/meta/*`, `/tables/*` et `/datasource/*` exigent l'en-tête `X-API-Key`.

### Autorisation Keycloak & Contrôle d'accès par table / action

Le microservice intègre un middleware `KeycloakPermissionMiddleware` qui intercepte les requêtes vers `/tables/{table}` et `/datasource/{datasource}/{table}`, décode le token JWT (`Authorization: Bearer <token>`) et vérifie que l'utilisateur possède les droits sur la table et l'action demandée :

| Méthode HTTP | Action vérifiée | Rôles / Scopes compatibles |
|---|---|---|
| `GET`, `HEAD` | `read` | `<table>:read`, `<table>:*`, `*:read`, `*:*`, `admin` |
| `POST` | `write` | `<table>:write`, `<table>:*`, `*:write`, `*:*`, `admin` |
| `PUT`, `PATCH` | `write` | `<table>:write`, `<table>:*`, `*:write`, `*:*`, `admin` |
| `DELETE` | `delete` | `<table>:delete`, `<table>:write`, `<table>:*`, `*:delete`, `*:*`, `admin` |

**Structures Keycloak prises en charge :**
1. **Rôles Realm & Client** : rôles granulaires au format `<table>:<action>` (ex : `users:read`, `orders:write`), ou rôles admin (`admin`, `realm-admin`, `superuser`).
2. **Keycloak Authorization Services (UMA)** : claim `authorization.permissions` avec `rsname` (nom de la table) et `scopes` (ex : `["read", "write"]`).

En cas d'absence de token ou token expiré : `401 Unauthorized`.  
En cas de droits insuffisants : `403 Forbidden` (`{"error": "Permission denied for action 'write' on table 'users'"}`).

Les routes publiques (`/healthz`, `/readyz`, `/docs`, `/openapi.json`) sont automatiquement exemptées.

Côté connexion à prestd, le microservice choisit automatiquement une
stratégie du middleware d'auth (`service/main.py::_build_auth`) :
`PRESTD_STATIC_TOKEN` si fourni, sinon `JWTAuth` à partir de
`PRESTD_USERNAME`/`PRESTD_PASSWORD` (login paresseux + re-login automatique
sur 401), sinon aucune auth.

## Lancer la stack complète en local (Postgres + prestd + microservice)

```bash
cd docker
docker compose up --build
```

prestd a besoin d'une table `prest_users` et d'un utilisateur pour que
l'auth JWT fonctionne. Une fois les conteneurs démarrés :

```bash
docker compose exec prestd prestd migrate up auth
docker compose exec postgres psql -U prest -d prest -c \
  "INSERT INTO prest_users (name, username, password) VALUES ('Prest User', 'prest', crypt('prest', gen_salt('bf')));"
```

Le microservice sera alors sur `http://localhost:8000`, prestd directement
sur `http://localhost:3000` (utile pour comparer/déboguer).

> Si `PREST_AUTH_ENABLED=false`, cette étape n'est pas nécessaire — retirez
> aussi `PRESTD_USERNAME`/`PRESTD_PASSWORD` du microservice.

## Tests

```bash
pytest
```

Les tests du client utilisent [respx](https://lundberg.github.io/respx/)
pour mocker les appels HTTP — aucun serveur prestd réel n'est nécessaire.

## Notes de fiabilité

Les endpoints et paramètres de prestd (`_page`, `_select`, `$gt`, `/auth`,
variables d'environnement `PREST_*`, etc.) ont été vérifiés sur la
documentation officielle (docs.prestd.com) au moment de la rédaction. prestd
évolue activement — en cas de comportement inattendu avec votre version,
vérifiez d'abord la doc officielle et `prestd --version`.

## Pistes d'extension

- **Cache** : ajouter un cache TTL en mémoire (ou Redis) dans
  `routers/records.py` sur les `GET` — le point d'entrée est déjà isolé.
- **Rate limiting** : middleware FastAPI (ex. `slowapi`) devant les routes
  `/tables/*`.
- **Requêtes nommées** : prestd supporte des requêtes SQL préparées côté
  serveur (dossier `queries/`) — un futur `client.run_query(name, **params)`
  peut s'y brancher directement.
- **Validation par table** : générer des modèles Pydantic à partir de
  `describe_table()` pour valider les payloads d'insertion/mise à jour.
