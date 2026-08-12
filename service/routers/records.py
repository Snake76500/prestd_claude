"""Proxy CRUD générique : /tables/{table} -> prestd `/{database}/{schema}/{table}`.

La syntaxe de filtre / pagination / tri est celle de prestd lui-même
(voir https://docs.prestd.com/api-reference/parameters) et est transmise
telle quelle : le microservice reste une façade fine et complète plutôt que
de réinventer un second DSL de filtres.

Exemples :
  GET /tables/users?active=$true&_order=-created_at&_page=1&_page_size=20
  GET /tables/users?_or=name=$ilike.%foo%||email=$ilike.%foo%
  POST /tables/users            body: {"name": "Ragnar", "active": true}
  PATCH /tables/users?id=42     body: {"active": false}
  DELETE /tables/users?id=42
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request

from prestd_client import PrestdClient

from ..dependencies import get_client, require_api_key

router = APIRouter(prefix="/tables", tags=["records"], dependencies=[Depends(require_api_key)])


def _forwarded_params(request: Request) -> dict[str, str]:
    """Tous les paramètres de la query string, transmis tels quels à prestd."""
    return dict(request.query_params)


@router.get("/{table}")
async def list_rows(table: str, request: Request, client: PrestdClient = Depends(get_client)):
    """Liste/filtre des lignes. Tout paramètre prestd fonctionne : `_page`,
    `_page_size`, `_select`, `_order`, `_or`, ou des filtres `champ=$operateur.valeur`."""
    qb = client.table(table)
    for field, value in _forwarded_params(request).items():
        qb.filter(field, value)
    return await qb.execute()


@router.post("/{table}", status_code=201)
async def create_row(
    table: str,
    payload: dict[str, Any] | list[dict[str, Any]],
    client: PrestdClient = Depends(get_client),
):
    """Insertion. `payload` peut être un objet (une ligne) ou une liste (insertion en lot)."""
    return await client.insert(table, payload)


@router.patch("/{table}")
async def update_rows(
    table: str,
    payload: dict[str, Any],
    request: Request,
    client: PrestdClient = Depends(get_client),
):
    """Mise à jour. Le corps contient les champs à modifier, les filtres
    viennent de la query string (comme pour le GET). Au moins un filtre est
    requis pour éviter un UPDATE inconditionnel."""
    filters = _forwarded_params(request)
    return await client.update(table, payload, filters)


@router.delete("/{table}")
async def delete_rows(table: str, request: Request, client: PrestdClient = Depends(get_client)):
    """Suppression filtrée par la query string. Au moins un filtre est requis."""
    filters = _forwarded_params(request)
    return await client.delete(table, filters)
