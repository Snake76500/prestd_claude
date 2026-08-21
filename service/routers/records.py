"""Proxy CRUD générique : /tables/{table} et /datasource/{datasource}/schema/{schema}/table/{table} -> prestd.

Fonctionne en miroir de l'API prestd et de prest _studio :
les filtres peuvent être saisis dans le champ `filter` (Swagger UI)
ou transmis directement en paramètres d'URL (ex: `user=$eq.TOTO`, `age=$gt.18`).
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from prestd_client import PrestdClient

from ..dependencies import get_client, require_api_key

router = APIRouter(tags=["records"], dependencies=[Depends(require_api_key)])

RESERVED_QUERY_PARAMS = {"filter"}


def _extract_filters(
    request: Request,
    filter_params: list[str] | str | None = None,
) -> dict[str, str]:
    """Extrait et combine tous les filtres :
    1. Paramètres directs passés dans la query string (ex: ?user=$eq.TOTO&age=$gte.18)
    2. Saisie explicite dans Swagger via le paramètre `filter` (ex: filter='user=$eq.TOTO')
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

    return filters


PREST_STUDIO_DOC = """
Recherche, filtre et pagine les enregistrements d'une table PostgreSQL via prestd.

Cet endpoint fonctionne en miroir direct de l'API prestd et du module **prest `_studio`**.

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
    filters = _extract_filters(request, filter_params=filter)
    for field, value in filters.items():
        qb.filter(field, value)
    return await qb.execute()


@router.post("/tables/{table}", status_code=201)
async def create_row(
    table: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    client: PrestdClient = Depends(get_client),
):
    """Insertion dans la table (base par défaut). `payload` peut être un objet (une ligne) ou une liste (en lot)."""
    return await client.insert(table, payload)


@router.patch(
    "/tables/{table}",
    summary="Mettre à jour des enregistrements filtrés (base par défaut)",
    description="Met à jour les lignes correspondant aux filtres spécifiés dans `filter` ou dans l'URL (ex: `?user=$eq.TOTO` ou `?id=42`).",
)
async def update_rows(
    table: str,
    payload: dict[str, Any],
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de mise à jour (ex: 'user=$eq.TOTO', 'id=42', 'role=guest')",
    ),
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour dans la table (base par défaut). Au moins un filtre est requis."""
    filters = _extract_filters(request, filter_params=filter)
    return await client.update(table, payload, filters)


@router.delete(
    "/tables/{table}",
    summary="Supprimer des enregistrements filtrés (base par défaut)",
    description="Supprime les lignes correspondant aux filtres spécifiés dans `filter` ou dans l'URL (ex: `?user=$eq.TOTO` ou `?id=42`).",
)
async def delete_rows(
    table: str,
    request: Request,
    filter: list[str] | None = Query(
        default=None,
        description="Filtre(s) de suppression (ex: 'user=$eq.TOTO', 'id=42', 'status=expired')",
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
    filters = _extract_filters(request, filter_params=filter)
    for field, value in filters.items():
        qb.filter(field, value)
    return await qb.execute()


@router.post("/datasource/{datasource}/schema/{schema}/table/{table}", status_code=201)
@router.post("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False, status_code=201)
@router.post("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False, status_code=201)
async def create_datasource_schema_row(
    datasource: str,
    schema: str,
    table: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    client: PrestdClient = Depends(get_client),
):
    """Insertion dans une table pour un datasource et schéma spécifiques (`payload` unique ou liste)."""
    return await client.insert(table, payload, datasource=datasource, schema=schema)


@router.patch(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    summary="Mettre à jour des enregistrements filtrés (datasource & schéma explicites)",
    description="Met à jour les lignes correspondant aux filtres spécifiés dans `filter` ou dans l'URL (ex: `?user=$eq.TOTO` ou `?id=42`).",
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
        description="Filtre(s) de mise à jour (ex: 'user=$eq.TOTO', 'id=42', 'status=pending')",
    ),
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour filtrée dans une table pour un datasource et schéma spécifiques. Au moins un filtre est requis."""
    filters = _extract_filters(request, filter_params=filter)
    return await client.update(table, payload, filters, datasource=datasource, schema=schema)


@router.delete(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    summary="Supprimer des enregistrements filtrés (datasource & schéma explicites)",
    description="Supprime les lignes correspondant aux filtres spécifiés dans `filter` ou dans l'URL (ex: `?user=$eq.TOTO` ou `?id=42`).",
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
        description="Filtre(s) de suppression (ex: 'user=$eq.TOTO', 'id=42', 'status=expired')",
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
