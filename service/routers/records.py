"""Proxy CRUD générique : /tables/{table} et /datasource/{datasource}/{table} -> prestd.

La syntaxe de filtre / pagination / tri est celle de prestd lui-même
(voir https://docs.prestd.com/api-reference/parameters) et est transmise
telle quelle : le microservice reste une façade fine et complète plutôt que
de réinventer un second DSL de filtres.

Exemples :
  GET /tables/users?active=$true&_order=-created_at&_page=1&_page_size=20
  GET /datasource/analytics_db/users?active=$true
  POST /tables/users                            body: {"name": "Ragnar", "active": true}
  POST /datasource/mydb/users                   body: {"name": "Ragnar", "active": true}
  PATCH /tables/users?id=42                     body: {"active": false}
  PATCH /datasource/mydb/users?id=42            body: {"active": false}
  DELETE /tables/users?id=42
  DELETE /datasource/mydb/users?id=42
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query, Request

from prestd_client import PrestdClient

from ..dependencies import get_client, require_api_key

router = APIRouter(tags=["records"], dependencies=[Depends(require_api_key)])

RESERVED_QUERY_PARAMS = {"search", "_page", "_page_size", "_order", "_select", "_or"}


def _forwarded_params(request: Request) -> dict[str, str]:
    """Tous les paramètres bruts de la query string, hors paramètres gérés explicitement."""
    return {k: v for k, v in request.query_params.items() if k not in RESERVED_QUERY_PARAMS}


def _apply_search_filter(qb: Any, search_expr: str) -> None:
    """Parse une expression search et l'applique au QueryBuilder.

    Prend en charge :
    - `champ=$operateur.valeur` (ex: `age=$gte.18`, `name=$ilike.%alice%`)
    - `champ=valeur` (ex: `active=true`, `role=admin`)
    - `champ:operateur:valeur` (ex: `age:gte:18`, `name:ilike:%alice%`)
    - multi-filtres séparés par virgule (hors clause $in) : `age=$gte.18,active=true`
    """
    expr = search_expr.strip()
    if not expr:
        return

    # Si plusieurs filtres sont combinés par virgule sans être dans un $in / $nin
    if "," in expr and "$in." not in expr and "$nin." not in expr and ":in:" not in expr and ":nin:" not in expr:
        sub_exprs = [s.strip() for s in expr.split(",") if s.strip()]
    else:
        sub_exprs = [expr]

    for item in sub_exprs:
        if "=" in item:
            field, val = item.split("=", 1)
            qb.filter(field.strip(), val.strip())
        elif ":" in item:
            parts = item.split(":", 2)
            if len(parts) == 3:
                field, op, val = parts
                op_clean = op if op.startswith("$") else f"${op}"
                qb.filter(field.strip(), f"{op_clean}.{val.strip()}")
            elif len(parts) == 2:
                field, val = parts
                qb.filter(field.strip(), val.strip())
        else:
            qb.filter("search", item)


def _apply_query_options(
    qb: Any,
    search: list[str] | str | None = None,
    page: int | None = None,
    page_size: int | None = None,
    order: str | None = None,
    select: str | None = None,
    or_condition: str | None = None,
    extra_params: dict[str, str] | None = None,
) -> None:
    """Applique l'ensemble des filtres, pagination, tri et search sur un QueryBuilder."""
    if search:
        search_list = [search] if isinstance(search, str) else search
        for s in search_list:
            _apply_search_filter(qb, s)

    if extra_params:
        for field, value in extra_params.items():
            qb.filter(field, value)

    if select:
        fields = [f.strip() for f in select.split(",") if f.strip()]
        if fields:
            qb.select(*fields)

    if order:
        order_fields = [o.strip() for o in order.split(",") if o.strip()]
        if order_fields:
            qb.order(*order_fields)

    if page is not None:
        qb.page(page, page_size)

    if or_condition:
        conds = [c.strip() for c in or_condition.split("||") if c.strip()]
        if conds:
            qb.or_(*conds)


SEARCH_OPENAPI_DOC = """
Recherche et extrait les enregistrements d'une table PostgreSQL via prestd avec support des opérateurs de filtre.

### 🔎 Utilisation du champ `search`
Le champ `search` permet d'appliquer un ou plusieurs filtres avec les opérateurs supportés par prestd (`champ=$operateur.valeur` ou `champ:operateur:valeur`) :

* **Égalité simple :**
  * `search=active=true`
  * `search=role=admin`
* **Comparaisons numériques & dates :**
  * Supérieur : `search=age=$gt.18` (ou `search=age:gt:18`)
  * Supérieur ou égal : `search=price=$gte.50` (ou `search=price:gte:50`)
  * Inférieur : `search=stock=$lt.5` (ou `search=stock:lt:5`)
  * Inférieur ou égal : `search=rating=$lte.3` (ou `search=rating:lte:3`)
  * Non égal : `search=status=$ne.archived` (ou `search=status:ne:archived`)
* **Recherche textuelle (LIKE / ILIKE) :**
  * Insensible à la casse : `search=name=$ilike.%dupont%` (ou `search=name:ilike:%dupont%`)
  * Sensible à la casse : `search=sku=$like.ABC%` (ou `search=sku:like:ABC%`)
  * Négations : `search=email=$nilike.%test%`
* **Appartenance à une liste ($in / $nin) :**
  * Dans la liste : `search=role=$in.admin,editor` (ou `search=role:in:admin,editor`)
  * Hors de la liste : `search=category=$nin.archived,spam`
* **Valeurs NULL et Booléens :**
  * Est NULL : `search=deleted_at=$null`
  * N'est pas NULL : `search=verified_at=$notnull`
  * Booléens : `search=is_active=$true`, `search=is_active=$false`

### 📄 Paramètres de pagination, tri et sélection
* `_page` : numéro de page (1-indexé)
* `_page_size` : nombre de lignes par page
* `_order` : colonnes de tri (ex: `-created_at,name` pour DESC sur `created_at` et ASC sur `name`)
* `_select` : projection de colonnes (ex: `id,name,email`)
* `_or` : clauses OU logiques (ex: `name=$ilike.%a%||email=$ilike.%a%`)
"""


# ==============================================================================
# Routes sur la base par défaut (/tables/{table})
# ==============================================================================


@router.get(
    "/tables/{table}",
    summary="Lister/filtrer les enregistrements (base par défaut)",
    description=SEARCH_OPENAPI_DOC,
)
async def list_rows(
    table: str,
    request: Request,
    search: list[str] | None = Query(
        default=None,
        description="Filtre(s) de recherche (ex: 'name=$ilike.%alice%', 'age=$gte.18', 'role=$in.admin,editor')",
        openapi_examples={
            "filtre_texte": {
                "summary": "Recherche textuelle insensible (ILIKE)",
                "value": "name=$ilike.%dupont%",
            },
            "comparaison_nombre": {
                "summary": "Filtre supérieur ou égal (>=)",
                "value": "age=$gte.18",
            },
            "liste_in": {
                "summary": "Appartenance à une liste (IN)",
                "value": "role=$in.admin,editor",
            },
            "valeur_nulle": {
                "summary": "Test IS NULL",
                "value": "deleted_at=$null",
            },
        },
    ),
    page: int | None = Query(default=None, alias="_page", description="Numéro de page", ge=1),
    page_size: int | None = Query(default=None, alias="_page_size", description="Nombre d'éléments par page", ge=1, le=1000),
    order: str | None = Query(default=None, alias="_order", description="Tri (ex: '-created_at,name')"),
    select: str | None = Query(default=None, alias="_select", description="Colonnes à sélectionner (ex: 'id,name,email')"),
    or_condition: str | None = Query(default=None, alias="_or", description="Clause OU logique (ex: 'title=$ilike.%a%||name=$ilike.%a%')"),
    client: PrestdClient = Depends(get_client),
):
    """Liste/filtre des lignes de la table (base par défaut)."""
    qb = client.table(table)
    _apply_query_options(
        qb,
        search=search,
        page=page,
        page_size=page_size,
        order=order,
        select=select,
        or_condition=or_condition,
        extra_params=_forwarded_params(request),
    )
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
    """Mise à jour dans la table (base par défaut). Le corps contient les champs à modifier, les filtres
    viennent de la query string. Au moins un filtre est requis."""
    filters = _forwarded_params(request)
    return await client.update(table, payload, filters)


@router.delete("/tables/{table}")
async def delete_rows(table: str, request: Request, client: PrestdClient = Depends(get_client)):
    """Suppression filtrée par la query string dans la table (base par défaut). Au moins un filtre est requis."""
    filters = _forwarded_params(request)
    return await client.delete(table, filters)


# ==============================================================================
# Routes avec datasource et schéma explicites (/datasource/{datasource}/schema/{schema}/table/{table})
# ==============================================================================


@router.get(
    "/datasource/{datasource}/schema/{schema}/table/{table}",
    summary="Lister/filtrer les enregistrements (datasource & schéma explicites)",
    description=SEARCH_OPENAPI_DOC,
)
@router.get("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def list_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    request: Request,
    search: list[str] | None = Query(
        default=None,
        description="Filtre(s) de recherche (ex: 'name=$ilike.%alice%', 'age=$gte.18', 'role=$in.admin,editor')",
        openapi_examples={
            "filtre_texte": {
                "summary": "Recherche textuelle insensible (ILIKE)",
                "value": "name=$ilike.%dupont%",
            },
            "comparaison_nombre": {
                "summary": "Filtre supérieur ou égal (>=)",
                "value": "age=$gte.18",
            },
            "liste_in": {
                "summary": "Appartenance à une liste (IN)",
                "value": "role=$in.admin,editor",
            },
            "valeur_nulle": {
                "summary": "Test IS NULL",
                "value": "deleted_at=$null",
            },
        },
    ),
    page: int | None = Query(default=None, alias="_page", description="Numéro de page (1-indexé)", ge=1),
    page_size: int | None = Query(default=None, alias="_page_size", description="Nombre d'éléments par page", ge=1, le=1000),
    order: str | None = Query(default=None, alias="_order", description="Tri (ex: '-created_at,name')"),
    select: str | None = Query(default=None, alias="_select", description="Colonnes à sélectionner (ex: 'id,name,email')"),
    or_condition: str | None = Query(default=None, alias="_or", description="Clause OU logique (ex: 'title=$ilike.%a%||name=$ilike.%a%')"),
    client: PrestdClient = Depends(get_client),
):
    """Liste/filtre des lignes pour un datasource et un schéma spécifiques."""
    qb = client.table(table, datasource=datasource, schema=schema)
    _apply_query_options(
        qb,
        search=search,
        page=page,
        page_size=page_size,
        order=order,
        select=select,
        or_condition=or_condition,
        extra_params=_forwarded_params(request),
    )
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
    """Mise à jour filtrée dans une table pour un datasource et schéma spécifiques. Au moins un filtre est requis."""
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
    """Suppression filtrée par la query string pour un datasource et schéma spécifiques. Au moins un filtre est requis."""
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
