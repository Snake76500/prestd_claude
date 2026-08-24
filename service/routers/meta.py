"""Endpoints de découverte de schéma en lecture seule (miroir des routes meta de prestd)."""
from __future__ import annotations

from fastapi import APIRouter, Depends

from prestd_client import PrestdClient

from ..dependencies import bearer_scheme, get_client, require_api_key

router = APIRouter(
    prefix="/meta",
    tags=["metadata"],
    dependencies=[Depends(require_api_key), Depends(bearer_scheme)],
)


@router.get("/databases")
async def list_databases(client: PrestdClient = Depends(get_client)):
    return await client.databases()


@router.get("/schemas")
async def list_schemas(client: PrestdClient = Depends(get_client)):
    return await client.schemas()


@router.get("/tables")
async def list_tables(client: PrestdClient = Depends(get_client)):
    return await client.tables()


@router.get("/tables/{table}")
async def describe_table(table: str, client: PrestdClient = Depends(get_client)):
    """Structure de la table (colonnes, types...) via GET /show/{db}/{schema}/{table}."""
    return await client.describe_table(table)


@router.get("/datasource/{datasource}/schema/{schema}/table/{table}")
@router.get("/datasource/{datasource}/tables/{table}")
@router.get("/datasources/{datasource}/tables/{table}", include_in_schema=False)
@router.get("/datasources/{datasource}/schemas/{schema}/tables/{table}", include_in_schema=False)
async def describe_datasource_table(
    datasource: str,
    table: str,
    schema: str | None = None,
    client: PrestdClient = Depends(get_client),
):
    """Structure de la table (colonnes, types...) pour un datasource donné via GET /show/{datasource}/{schema}/{table}."""
    return await client.describe_table(table, database=datasource, schema=schema)

