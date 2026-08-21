import math
from typing import Any

from fastapi import APIRouter, Body, Depends, Query, Request

from prestd_client import PrestdClient

from ..dependencies import get_client, require_api_key

router = APIRouter(tags=["records"], dependencies=[Depends(require_api_key)])

RESERVED_QUERY_PARAMS = {"filter"}


def _extract_filters(
    request: Request,
    filter_params: list[str] | str | None = None,
    _select: str | None = None,
    _order: str | None = None,
    _page: int | None = None,
    _page_size: int | None = None,
    _distinct: bool | None = None,
    _groupby: str | None = None,
    _count: str | None = None,
    _or: str | None = None,
) -> dict[str, str]:
    """Extrait et combine tous les filtres :
    1. Paramètres directs passés dans la query string (ex: ?user=$eq.TOTO&age=$gte.18)
    2. Saisie explicite dans Swagger via le paramètre `filter` (ex: filter='user=$eq.TOTO')
    3. Paramètres système explicitement renseignés dans Swagger (_page, _page_size, etc.)
    """
    filters: dict[str, str] = {}

    # 1. Paramètres directs d'URL (ex: ?user=$eq.TOTO&status=active)
    for k, v in request.query_params.items():
        if k not in RESERVED_QUERY_PARAMS:
            filters[k] = v

    # 2. Paramètre(s) filter saisis dans Swagger (ex: filter='user=$eq.TOTO')
    if filter_params:
        items = [filter_params] if isinstance(filter_params, str) else filter_params
        for item in items:
            item = item.strip()
            if not item:
                continue
            if "=" in item:
                k, v = item.split("=", 1)
                filters[k.strip()] = v.strip()
            elif ":" in item:
                parts = item.split(":", 2)
                if len(parts) == 3:
                    field, op, val = parts
                    op_clean = op if op.startswith("$") else f"${op}"
                    filters[field.strip()] = f"{op_clean}.{val.strip()}"
                elif len(parts) == 2:
                    field, val = parts
                    filters[field.strip()] = val.strip()

    # 3. Paramètres système FastAPI explicites (s'ils n'ont pas été remplacés par filter)
    if _select and "_select" not in filters:
        filters["_select"] = _select
    if _order and "_order" not in filters:
        filters["_order"] = _order
    if _page is not None and "_page" not in filters:
        filters["_page"] = str(_page)
    if _page_size is not None and "_page_size" not in filters:
        filters["_page_size"] = str(_page_size)
    if _distinct is not None and "_distinct" not in filters:
        filters["_distinct"] = "true" if _distinct else "false"
    if _groupby and "_groupby" not in filters:
        filters["_groupby"] = _groupby
    if _count and "_count" not in filters:
        filters["_count"] = _count
    if _or and "_or" not in filters:
        filters["_or"] = _or

    # 4. Normalisation des alias de pagination
    if "page" in filters and "_page" not in filters:
        filters["_page"] = filters.pop("page")
    if "page_size" in filters and "_page_size" not in filters:
        filters["_page_size"] = filters.pop("page_size")
    if "limit" in filters and "_page_size" not in filters:
        filters["_page_size"] = filters.pop("limit")

    # prestd exige _page pour activer la pagination quand _page_size est fourni
    if "_page_size" in filters and "_page" not in filters:
        filters["_page"] = "1"

    return filters


async def _get_total_count(
    client: PrestdClient,
    table: str,
    filters: dict[str, str],
    datasource: str | None = None,
    schema: str | None = None,
) -> int:
    """Exécute une requête COUNT(*) sur prestd avec les filtres applicables."""
    count_qb = client.table(table, datasource=datasource, schema=schema)
    for field, value in filters.items():
        if not field.startswith("_"):
            count_qb.filter(field, value)
    count_qb.count("*")
    try:
        res = await count_qb.execute()
        if res and isinstance(res, list) and len(res) > 0 and isinstance(res[0], dict):
            val = list(res[0].values())[0]
            return int(val)
    except Exception:
        pass
    return 0


async def _execute_paginated_get(
    qb: Any,
    client: PrestdClient,
    table: str,
    filters: dict[str, str],
    datasource: str | None = None,
    schema: str | None = None,
) -> dict[str, Any] | list[dict[str, Any]]:
    """Exécute la requête GET et renvoie la réponse encapsulée avec métadonnées de pagination."""
    if "_count" in filters:
        return await qb.execute()

    rows = await qb.execute()

    try:
        page = int(filters.get("_page", "1"))
    except ValueError:
        page = 1

    has_page_size = "_page_size" in filters
    if has_page_size:
        try:
            page_size = int(filters["_page_size"])
        except ValueError:
            page_size = len(rows) if len(rows) > 0 else 10
    else:
        page_size = len(rows) if len(rows) > 0 else 10

    # Optimisation : si page 1 et moins de résultats que page_size, total_rows est directement connu
    if page == 1 and len(rows) < page_size:
        total_rows = len(rows)
    else:
        total_rows = await _get_total_count(client, table, filters, datasource=datasource, schema=schema)
        if total_rows < len(rows):
            total_rows = len(rows)

    if total_rows == 0:
        total_pages = 0
    elif page_size > 0:
        total_pages = math.ceil(total_rows / page_size)
    else:
        total_pages = 1

    return {
        "data": rows,
        "page": page,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": total_pages,
    }


PREST_STUDIO_DOC = """
Recherche, filtre et pagine les enregistrements d'une table PostgreSQL via prestd.

Cet endpoint fonctionne en miroir direct de l'API prestd et du module **prest `_studio`**.

---

### 📦 Format de la réponse GET
La réponse est encapsulée dans une structure de pagination enrichie :
* `data` : Liste des enregistrements de la page demandée
* `page` : Numéro de la page actuelle (1-indexé)
* `page_size` : Nombre d'éléments par page
* `total_rows` : Nombre total d'enregistrements (rows) correspondant aux filtres
* `total_pages` : Nombre total de pages disponibles

---

### ⚡ Saisie des filtres (Opérateurs prestd / _studio)
Vous pouvez saisir vos filtres dans le champ **`filter`** de Swagger ou directement dans l'URL sous la forme `nom_colonne=$operateur.valeur` ou `nom_colonne=valeur` :

| Opérateur | Syntaxe d'exemple | Description SQL équivalente |
|---|---|---|
| **Égalité** | `user=TOTO` ou `user=$eq.TOTO` | `WHERE "user" = 'TOTO'` |
| **Différent** | `status=$ne.archived` | `WHERE "status" != 'archived'` |
| **Supérieur (>)** | `age=$gt.18` | `WHERE "age" > 18` |
| **Supérieur ou égal (>=)** | `price=$gte.49.99` | `WHERE "price" >= 49.99` |
| **Inférieur (<)** | `stock=$lt.5` | `WHERE "stock" < 5` |
| **Inférieur ou égal (<=)** | `rating=$lte.3` | `WHERE "rating" <= 3` |
| **Dans la liste ($in)** | `role=$in.admin,editor` | `WHERE "role" IN ('admin', 'editor')` |
| **Hors de la liste ($nin)** | `role=$nin.guest,bot` | `WHERE "role" NOT IN ('guest', 'bot')` |
| **Recherche ILIKE (insensible)** | `name=$ilike.%TOTO%` | `WHERE "name" ILIKE '%TOTO%'` |
| **Recherche LIKE (sensible)** | `sku=$like.ABC%` | `WHERE "sku" LIKE 'ABC%'` |
| **Négation LIKE / ILIKE** | `email=$nilike.%test%` | `WHERE "email" NOT ILIKE '%test%'` |
| **Valeur NULL ($null)** | `deleted_at=$null` | `WHERE "deleted_at" IS NULL` |
| **Valeur non NULL ($notnull)** | `verified_at=$notnull` | `WHERE "verified_at" IS NOT NULL` |
| **Booléen vrai ($true)** | `is_active=$true` | `WHERE "is_active" IS TRUE` |
| **Booléen faux ($false)** | `is_active=$false` | `WHERE "is_active" IS FALSE` |

---

### 🛠️ Paramètres système prestd
* `_select` : Restriction des colonnes (ex: `_select=id,name,email`)
* `_order` : Tri des résultats, préfixé par `-` pour DESC (ex: `_order=-created_at,name`)
* `_page` : Numéro de page (1-indexé)
* `_page_size` : Nombre de lignes par page
* `_distinct` : Déduplication `true`/`false`
* `_groupby` : Groupement (ex: `_groupby=status`)
* `_count` : Comptage (ex: `_count=*`)
* `_or` : Combinaison OU logique (ex: `_or=name=$ilike.%TOTO%||email=$ilike.%TOTO%`)
"""

PREST_CREATE_DOC = """
Insère un ou plusieurs enregistrements dans une table PostgreSQL via prestd.

---

### 📦 Format du payload (Corps de la requête / Body)
Le `payload` JSON transmis dans le body peut prendre deux formes :

1. **Insertion d'une ligne unique (Objet JSON)** :
   ```json
   {
     "name": "Alice",
     "email": "alice@example.com",
     "role": "admin",
     "active": true
   }
   ```

2. **Insertion en lot / Batch Insert (Liste d'objets JSON)** :
   ```json
   [
     { "name": "Bob", "email": "bob@example.com", "role": "user" },
     { "name": "Charlie", "email": "charlie@example.com", "role": "editor" }
   ]
   ```

---

### ⚡ Réponses
* **201 Created** : Renvoie le ou les enregistrements créés avec leurs identifiants auto-générés.
"""

PREST_UPDATE_DOC = """
Mise à jour d'un ou plusieurs enregistrements filtrés d'une table PostgreSQL via prestd.

---

### ⚠️ Condition obligatoire
Au moins un filtre est requis dans le paramètre **`filter`** ou directement dans l'URL pour identifier les lignes à modifier.

---

### ⚡ Exemples de filtres de sélection
Vous pouvez saisir vos filtres dans le champ **`filter`** de Swagger UI ou directement dans l'URL (ex: `id=42` ou `status=$eq.pending`) :

* `id=42` : Met à jour la ligne ayant l'ID 42 (`WHERE "id" = 42`)
* `user=$eq.TOTO` : Met à jour les lignes de l'utilisateur TOTO (`WHERE "user" = 'TOTO'`)
* `status=$in.pending,draft` : Met à jour les lignes dont le statut est pending ou draft (`WHERE "status" IN ('pending', 'draft')`)
"""

PREST_DELETE_DOC = """
Suppression d'un ou plusieurs enregistrements filtrés d'une table PostgreSQL via prestd.

---

### ⚠️ Condition obligatoire
Au moins un filtre est requis dans le paramètre **`filter`** ou directement dans l'URL pour éviter toute suppression inconditionnelle.

---

### ⚡ Exemples de filtres de sélection
Vous pouvez saisir vos filtres dans le champ **`filter`** de Swagger UI ou directement dans l'URL (ex: `id=42` ou `status=$eq.expired`) :

* `id=42` : Supprime la ligne ayant l'ID 42 (`WHERE "id" = 42`)
* `user=$eq.TOTO` : Supprime les lignes de l'utilisateur TOTO (`WHERE "user" = 'TOTO'`)
* `expired_at=$lt.2026-01-01` : Supprime les lignes expirées avant la date (`WHERE "expired_at" < '2026-01-01'`)
"""


# ==============================================================================
# Routes sur la base par défaut (/tables/{table})
# ==============================================================================


@router.get(
    "/tables/{table}",
    summary="Lister et filtrer les enregistrements (base par défaut)",
    description=PREST_STUDIO_DOC,
)
async def list_rows(
    table: str,
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de colonne (ex: 'user=$eq.TOTO', 'age=$gte.18', 'active=true', 'name=$ilike.%alice%')",
        openapi_examples={
            "egalite": {
                "summary": "Égalité ($eq)",
                "value": "user=$eq.TOTO",
            },
            "comparaison": {
                "summary": "Comparaison ($gte)",
                "value": "age=$gte.18",
            },
            "recherche_texte": {
                "summary": "Recherche textuelle ($ilike)",
                "value": "name=$ilike.%TOTO%",
            },
            "liste_in": {
                "summary": "Appartenance ($in)",
                "value": "role=$in.admin,editor",
            },
        },
    ),
    _select: str | None = Query(default=None, description="Colonnes à sélectionner (ex: 'id,name,email')"),
    _order: str | None = Query(default=None, description="Tri, préfixer par '-' pour DESC (ex: '-created_at,name')"),
    _page: int | None = Query(default=None, description="Numéro de page (1-indexé)", ge=1),
    _page_size: int | None = Query(default=None, description="Nombre d'éléments par page", ge=1, le=1000),
    _distinct: bool | None = Query(default=None, description="Déduplication des résultats (SELECT DISTINCT)"),
    _groupby: str | None = Query(default=None, description="Grouper par colonne(s)"),
    _count: str | None = Query(default=None, description="Compter les enregistrements (ex: '*' ou 'id')"),
    _or: str | None = Query(default=None, description="Conditions OU logiques (ex: 'name=$ilike.%a%||email=$ilike.%a%')"),
    client: PrestdClient = Depends(get_client),
):
    """Liste/filtre des lignes de la table (base par défaut)."""
    qb = client.table(table)
    filters = _extract_filters(
        request,
        filter_params=filter,
        _select=_select,
        _order=_order,
        _page=_page,
        _page_size=_page_size,
        _distinct=_distinct,
        _groupby=_groupby,
        _count=_count,
        _or=_or,
    )
    for field, value in filters.items():
        qb.filter(field, value)
    return await _execute_paginated_get(qb, client, table, filters)


@router.post(
    "/tables/{table}",
    status_code=201,
    summary="Créer un ou plusieurs enregistrements (base par défaut)",
    description=PREST_CREATE_DOC,
)
async def create_row(
    table: str,
    payload: dict[str, Any] | list[dict[str, Any]] = Body(
        ...,
        description="Données à insérer : un objet JSON (ligne unique) ou une liste d'objets (insertion en lot)",
        openapi_examples={
            "ligne_unique": {
                "summary": "Insertion d'une ligne unique",
                "value": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "role": "admin",
                    "active": True,
                },
            },
            "insertion_lot": {
                "summary": "Insertion en lot (Batch Insert)",
                "value": [
                    {"name": "Bob", "email": "bob@example.com", "role": "user"},
                    {"name": "Charlie", "email": "charlie@example.com", "role": "editor"},
                ],
            },
        },
    ),
    client: PrestdClient = Depends(get_client),
):
    """Insertion dans la table (base par défaut). `payload` peut être un objet (une ligne) ou une liste (en lot)."""
    return await client.insert(table, payload)


@router.patch(
    "/tables/{table}",
    summary="Mettre à jour des enregistrements filtrés (base par défaut)",
    description=PREST_UPDATE_DOC,
)
async def update_rows(
    table: str,
    payload: dict[str, Any],
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de ciblage des enregistrements à mettre à jour (ex: 'id=42', 'user=$eq.TOTO', 'status=pending')",
        openapi_examples={
            "par_id": {
                "summary": "Filtre par ID",
                "value": "id=42",
            },
            "egalite": {
                "summary": "Égalité ($eq)",
                "value": "user=$eq.TOTO",
            },
            "comparaison": {
                "summary": "Comparaison ($gte)",
                "value": "age=$gte.18",
            },
            "liste_in": {
                "summary": "Appartenance ($in)",
                "value": "status=$in.pending,draft",
            },
        },
    ),
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour dans la table (base par défaut). Au moins un filtre est requis."""
    filters = _extract_filters(request, filter_params=filter)
    return await client.update(table, payload, filters)


@router.delete(
    "/tables/{table}",
    summary="Supprimer des enregistrements filtrés (base par défaut)",
    description=PREST_DELETE_DOC,
)
async def delete_rows(
    table: str,
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de ciblage des enregistrements à supprimer (ex: 'id=42', 'user=$eq.TOTO', 'status=expired')",
        openapi_examples={
            "par_id": {
                "summary": "Filtre par ID",
                "value": "id=42",
            },
            "egalite": {
                "summary": "Égalité ($eq)",
                "value": "user=$eq.TOTO",
            },
            "comparaison": {
                "summary": "Comparaison ($lt)",
                "value": "expired_at=$lt.2026-01-01",
            },
            "liste_in": {
                "summary": "Appartenance ($in)",
                "value": "status=$in.expired,archived",
            },
        },
    ),
    client: PrestdClient = Depends(get_client),
):
    """Suppression filtrée dans la table (base par défaut). Au moins un filtre est requis."""
    filters = _extract_filters(request, filter_params=filter)
    return await client.delete(table, filters)


# ==============================================================================
# Routes avec datasource et schéma explicites (/datasource/{datasource}/schema/{schema}/table/{table})
# ==============================================================================


@router.get(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    summary="Lister et filtrer les enregistrements (datasource & schéma explicites)",
    description=PREST_STUDIO_DOC,
)
@router.get("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def list_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de colonne (ex: 'user=$eq.TOTO', 'age=$gte.18', 'active=true', 'name=$ilike.%alice%')",
        openapi_examples={
            "egalite": {
                "summary": "Égalité ($eq)",
                "value": "user=$eq.TOTO",
            },
            "comparaison": {
                "summary": "Comparaison ($gte)",
                "value": "age=$gte.18",
            },
            "recherche_texte": {
                "summary": "Recherche textuelle ($ilike)",
                "value": "name=$ilike.%TOTO%",
            },
            "liste_in": {
                "summary": "Appartenance ($in)",
                "value": "role=$in.admin,editor",
            },
        },
    ),
    _select: str | None = Query(default=None, description="Colonnes à sélectionner (ex: 'id,name,email')"),
    _order: str | None = Query(default=None, description="Tri, préfixer par '-' pour DESC (ex: '-created_at,name')"),
    _page: int | None = Query(default=None, description="Numéro de page (1-indexé)", ge=1),
    _page_size: int | None = Query(default=None, description="Nombre d'éléments par page", ge=1, le=1000),
    _distinct: bool | None = Query(default=None, description="Déduplication des résultats (SELECT DISTINCT)"),
    _groupby: str | None = Query(default=None, description="Grouper par colonne(s)"),
    _count: str | None = Query(default=None, description="Compter les enregistrements (ex: '*' ou 'id')"),
    _or: str | None = Query(default=None, description="Conditions OU logiques (ex: 'name=$ilike.%a%||email=$ilike.%a%')"),
    client: PrestdClient = Depends(get_client),
):
    """Liste/filtre des lignes pour un datasource et un schéma spécifiques."""
    qb = client.table(table, datasource=datasource, schema=schema)
    filters = _extract_filters(
        request,
        filter_params=filter,
        _select=_select,
        _order=_order,
        _page=_page,
        _page_size=_page_size,
        _distinct=_distinct,
        _groupby=_groupby,
        _count=_count,
        _or=_or,
    )
    for field, value in filters.items():
        qb.filter(field, value)
    return await _execute_paginated_get(qb, client, table, filters, datasource=datasource, schema=schema)


# ==============================================================================
# Alias de compatibilité (/datasource/{datasource}/{table})
# ==============================================================================


@router.get("/datasource/{datasource}/{table}", include_in_schema=False)
@router.get("/datasource/{datasource}/tables/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/tables/{table}", include_in_schema=False)
async def list_datasource_rows(
    datasource: str,
    table: str,
    request: Request,
    filter: list[str] | None = Query(default=None),
    client: PrestdClient = Depends(get_client),
):
    qb = client.table(table, datasource=datasource)
    filters = _extract_filters(request, filter_params=filter)
    for field, value in filters.items():
        qb.filter(field, value)
    return await _execute_paginated_get(qb, client, table, filters, datasource=datasource)


@router.post(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    status_code=201,
    summary="Créer un ou plusieurs enregistrements (datasource & schéma explicites)",
    description=PREST_CREATE_DOC,
)
@router.post("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False, status_code=201)
@router.post("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False, status_code=201)
async def create_datasource_schema_row(
    datasource: str,
    schema: str,
    table: str,
    payload: dict[str, Any] | list[dict[str, Any]] = Body(
        ...,
        description="Données à insérer : un objet JSON (ligne unique) ou une liste d'objets (insertion en lot)",
        openapi_examples={
            "ligne_unique": {
                "summary": "Insertion d'une ligne unique",
                "value": {
                    "name": "Alice",
                    "email": "alice@example.com",
                    "role": "admin",
                    "active": True,
                },
            },
            "insertion_lot": {
                "summary": "Insertion en lot (Batch Insert)",
                "value": [
                    {"name": "Bob", "email": "bob@example.com", "role": "user"},
                    {"name": "Charlie", "email": "charlie@example.com", "role": "editor"},
                ],
            },
        },
    ),
    client: PrestdClient = Depends(get_client),
):
    """Insertion dans une table pour un datasource et schéma spécifiques (`payload` unique ou liste)."""
    return await client.insert(table, payload, datasource=datasource, schema=schema)


@router.patch(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    summary="Mettre à jour des enregistrements filtrés (datasource & schéma explicites)",
    description=PREST_UPDATE_DOC,
)
@router.patch("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.patch("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def update_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    payload: dict[str, Any],
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de ciblage des enregistrements à mettre à jour (ex: 'id=42', 'user=$eq.TOTO', 'status=pending')",
        openapi_examples={
            "par_id": {
                "summary": "Filtre par ID",
                "value": "id=42",
            },
            "egalite": {
                "summary": "Égalité ($eq)",
                "value": "user=$eq.TOTO",
            },
            "comparaison": {
                "summary": "Comparaison ($gte)",
                "value": "age=$gte.18",
            },
            "liste_in": {
                "summary": "Appartenance ($in)",
                "value": "status=$in.pending,draft",
            },
        },
    ),
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour filtrée dans une table pour un datasource et schéma spécifiques. Au moins un filtre est requis."""
    filters = _extract_filters(request, filter_params=filter)
    return await client.update(table, payload, filters, datasource=datasource, schema=schema)


@router.delete(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    summary="Supprimer des enregistrements filtrés (datasource & schéma explicites)",
    description=PREST_DELETE_DOC,
)
@router.delete("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.delete("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def delete_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de ciblage des enregistrements à supprimer (ex: 'id=42', 'user=$eq.TOTO', 'status=expired')",
        openapi_examples={
            "par_id": {
                "summary": "Filtre par ID",
                "value": "id=42",
            },
            "egalite": {
                "summary": "Égalité ($eq)",
                "value": "user=$eq.TOTO",
            },
            "comparaison": {
                "summary": "Comparaison ($lt)",
                "value": "expired_at=$lt.2026-01-01",
            },
            "liste_in": {
                "summary": "Appartenance ($in)",
                "value": "status=$in.expired,archived",
            },
        },
    ),
    client: PrestdClient = Depends(get_client),
):
    """Suppression filtrée par la query string pour un datasource et schéma spécifiques. Au moins un filtre est requis."""
    filters = _extract_filters(request, filter_params=filter)
    return await client.delete(table, filters, datasource=datasource, schema=schema)


# ==============================================================================
# Alias de compatibilité (/datasource/{datasource}/{table})
# ==============================================================================


@router.get("/datasource/{datasource}/{table}", include_in_schema=False)
@router.get("/datasource/{datasource}/tables/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/tables/{table}", include_in_schema=False)
async def list_datasource_rows(
    datasource: str,
    table: str,
    request: Request,
    filter: list[str] | None = Query(default=None),
    client: PrestdClient = Depends(get_client),
):
    qb = client.table(table, datasource=datasource)
    filters = _extract_filters(request, filter_params=filter)
    for field, value in filters.items():
        qb.filter(field, value)
    return await qb.execute()


@router.post("/datasource/{datasource}/{table}", status_code=201, include_in_schema=False)
@router.post("/datasource/{datasource}/tables/{table}", include_in_schema=False, status_code=201)
@router.post("/datasources/{datasource}/{table}", include_in_schema=False, status_code=201)
@router.post("/datasources/{datasource}/tables/{table}", include_in_schema=False, status_code=201)
async def create_datasource_row(
    datasource: str,
    table: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    client: PrestdClient = Depends(get_client),
):
    return await client.insert(table, payload, datasource=datasource)


@router.patch("/datasource/{datasource}/{table}", include_in_schema=False)
@router.patch("/datasource/{datasource}/tables/{table}", include_in_schema=False)
@router.patch("/datasources/{datasource}/{table}", include_in_schema=False)
@router.patch("/datasources/{datasource}/tables/{table}", include_in_schema=False)
async def update_datasource_rows(
    datasource: str,
    table: str,
    payload: dict[str, Any],
    request: Request,
    filter: list[str] | None = Query(default=None),
    client: PrestdClient = Depends(get_client),
):
    filters = _extract_filters(request, filter_params=filter)
    return await client.update(table, payload, filters, datasource=datasource)


@router.delete("/datasource/{datasource}/{table}", include_in_schema=False)
@router.delete("/datasource/{datasource}/tables/{table}", include_in_schema=False)
@router.delete("/datasources/{datasource}/{table}", include_in_schema=False)
@router.delete("/datasources/{datasource}/tables/{table}", include_in_schema=False)
async def delete_datasource_rows(
    datasource: str,
    table: str,
    request: Request,
    filter: list[str] | None = Query(default=None),
    client: PrestdClient = Depends(get_client),
):
    filters = _extract_filters(request, filter_params=filter)
    return await client.delete(table, filters, datasource=datasource)
