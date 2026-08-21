"""Proxy CRUD générique : /tables/{table} et /datasource/{datasource}/schema/{schema}/table/{table} -> prestd.

Fonctionne exactement comme l'API native de prestd et le module _studio :
les paramètres de filtrage (ex: `user=$eq.TOTO`, `age=$gt.18`, `name=$ilike.%foo%`)
et les paramètres système (`_select`, `_order`, `_page`, `_page_size`, `_or`, etc.)
sont transmis directement et fidèlement au moteur prestd.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from prestd_client import PrestdClient

from ..dependencies import get_client, require_api_key

router = APIRouter(tags=["records"], dependencies=[Depends(require_api_key)])


def _forwarded_params(request: Request) -> dict[str, str]:
    """Transmet l'intégralité des paramètres de la query string tels quels à prestd (miroir prest _studio)."""
    return dict(request.query_params)


PREST_STUDIO_DOC = """
Recherche, filtre et pagine les enregistrements d'une table PostgreSQL via prestd.

Cet endpoint fonctionne en miroir direct de l'API prestd et du module **prest `_studio`**.

---

### ⚡ Filtres par colonne (Opérateurs prestd / _studio)
Ajoutez directement vos filtres sous la forme `nom_colonne=$operateur.valeur` ou `nom_colonne=valeur` dans la query string :

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
    for field, value in _forwarded_params(request).items():
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


@router.patch("/tables/{table}")
async def update_rows(
    table: str,
    payload: dict[str, Any],
    request: Request,
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour dans la table (base par défaut). Les filtres viennent de la query string (ex: `?id=42` ou `?user=$eq.TOTO`). Au moins un filtre est requis."""
    filters = _forwarded_params(request)
    return await client.update(table, payload, filters)


@router.delete("/tables/{table}")
async def delete_rows(table: str, request: Request, client: PrestdClient = Depends(get_client)):
    """Suppression filtrée par la query string dans la table (base par défaut, ex: `?id=42` ou `?user=$eq.TOTO`). Au moins un filtre est requis."""
    filters = _forwarded_params(request)
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
    for field, value in _forwarded_params(request).items():
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


@router.patch("/datasource/{datasource}/schema/{schema}/table/{table}")
@router.patch("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.patch("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def update_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    payload: dict[str, Any],
    request: Request,
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour filtrée dans une table pour un datasource et schéma spécifiques (ex: `?user=$eq.TOTO`). Au moins un filtre est requis."""
    filters = _forwarded_params(request)
    return await client.update(table, payload, filters, datasource=datasource, schema=schema)


@router.delete("/datasource/{datasource}/schema/{schema}/table/{table}")
@router.delete("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.delete("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def delete_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    request: Request,
    client: PrestdClient = Depends(get_client),
):
    """Suppression filtrée par la query string pour un datasource et schéma spécifiques (ex: `?user=$eq.TOTO`). Au moins un filtre est requis."""
    filters = _forwarded_params(request)
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
    client: PrestdClient = Depends(get_client),
):
    qb = client.table(table, datasource=datasource)
    for field, value in _forwarded_params(request).items():
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
    client: PrestdClient = Depends(get_client),
):
    filters = _forwarded_params(request)
    return await client.update(table, payload, filters, datasource=datasource)


@router.delete("/datasource/{datasource}/{table}", include_in_schema=False)
@router.delete("/datasource/{datasource}/tables/{table}", include_in_schema=False)
@router.delete("/datasources/{datasource}/{table}", include_in_schema=False)
@router.delete("/datasources/{datasource}/tables/{table}", include_in_schema=False)
async def delete_datasource_rows(
    datasource: str,
    table: str,
    request: Request,
    client: PrestdClient = Depends(get_client),
):
    filters = _forwarded_params(request)
    return await client.delete(table, filters, datasource=datasource)
