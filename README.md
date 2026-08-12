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

### Façade synchrone (scripts, notebooks)

```python
from prestd_client import SyncPrestdClient

with SyncPrestdClient("http://localhost:3000", default_database="mydb") as client:
    client.login("prest", "prest")
    rows = client.select("users", active="true", order="-created_at", page=1, page_size=10)
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
| GET | `/meta/tables/{table}` | structure d'une table |
| GET | `/tables/{table}?...` | liste/filtre (syntaxe prestd transmise telle quelle) |
| POST | `/tables/{table}` | insertion (objet ou liste) |
| PATCH | `/tables/{table}?id=...` | mise à jour filtrée |
| DELETE | `/tables/{table}?id=...` | suppression filtrée |

Si `SERVICE_API_KEY` est définie dans l'environnement, toutes les routes
`/meta/*` et `/tables/*` exigent l'en-tête `X-API-Key`.

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
