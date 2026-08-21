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

from fastapi import APIRouter, Depends, Request

from prestd_client import PrestdClient

from ..dependencies import get_client, require_api_key

router = APIRouter(tags=["records"], dependencies=[Depends(require_api_key)])


def _forwarded_params(request: Request) -> dict[str, str]:
    """Tous les paramètres de la query string, transmis tels quels à prestd."""
    return dict(request.query_params)


# ==============================================================================
# Routes sur la base par défaut (/tables/{table})
# ==============================================================================


@router.get("/tables/{table}")
async def list_rows(table: str, request: Request, client: PrestdClient = Depends(get_client)):
    """Liste/filtre des lignes de la table (base par défaut). Tout paramètre prestd fonctionne :
    `_page`, `_page_size`, `_select`, `_order`, `_or`, ou des filtres `champ=$operateur.valeur`."""
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


@router.get("/datasource/{datasource}/schema/{schema}/table/{table}")
@router.get("/datasource/{datasource}/schema/{schema}/tables/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def list_datasource_schema_rows(
    datasource: str,
    schema: str,
    table: str,
    request: Request,
    client: PrestdClient = Depends(get_client),
):
    """Liste/filtre des lignes pour un datasource et un schéma spécifiques. Tout paramètre prestd fonctionne :
    `_page`, `_page_size`, `_select`, `_order`, `_or`, ou des filtres `champ=$operateur.valeur`."""
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
