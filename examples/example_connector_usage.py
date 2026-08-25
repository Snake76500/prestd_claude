"""Exemple complet d'utilisation du connecteur Python et de la dépendance FastAPI.

Ce fichier illustre :
1. L'utilisation programmatique du connecteur asynchrone `PrestdServiceConnector`.
2. L'utilisation du connecteur synchrone `SyncPrestdServiceConnector`.
3. L'intégration comme dépendance `Depends(get_service_connector())` dans une application FastAPI cliente.

Lancer le script :
    python examples/example_connector_usage.py
"""
from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Depends, FastAPI
from prestd_client import (
    PaginatedResponse,
    PrestdServiceConnector,
    SyncPrestdServiceConnector,
    get_service_connector,
)

MICROSERVICE_URL = "http://localhost:8000"


# ==============================================================================
# 1. Utilisation Programmatique Asynchrone (PrestdServiceConnector)
# ==============================================================================
async def demo_async_connector() -> None:
    print("\n--- 1. Démo PrestdServiceConnector (Asynchrone) ---")

    async with PrestdServiceConnector(
        base_url=MICROSERVICE_URL,
        api_key=None,  # Optionnel : "ma_cle_api_secrete"
        token=None,    # Optionnel : token Keycloak
    ) as connector:
        # Santé & Métadonnées
        health = await connector.health()
        print("Santé du microservice :", health)

        # SELECT paginé avec filtres
        res: PaginatedResponse = (
            await connector.table("users")
            .filter(role="$eq.admin", active="true")
            .select("id", "name", "email")
            .order_by("-created_at")
            .page(page=1, page_size=5)
            .list()
        )
        print(f"Lignes trouvées ({res.total_rows} au total, page {res.page}/{res.total_pages}) :")
        for row in res.data:
            print("  -", row)

        # Insertion (Ligne unique ou lot)
        # created = await connector.table("users").create({"name": "Alice", "role": "admin"})

        # Mise à jour filtrée
        # await connector.table("users").filter(id="42").update({"active": False})

        # Suppression filtrée
        # await connector.table("users").delete(filters={"id": "42"})


# ==============================================================================
# 2. Utilisation Programmatique Synchrone (SyncPrestdServiceConnector)
# ==============================================================================
def demo_sync_connector() -> None:
    print("\n--- 2. Démo SyncPrestdServiceConnector (Synchrone) ---")

    with SyncPrestdServiceConnector(base_url=MICROSERVICE_URL) as connector:
        health = connector.health()
        print("Santé :", health)

        # res = connector.list_rows("users", page=1, page_size=5)
        # print("Total rows :", res.total_rows)


# ==============================================================================
# 3. Dépendance FastAPI dans une Application Cliente
# ==============================================================================
app = FastAPI(title="Mon Application Métier Cliente")


@app.get("/api/my-users")
async def get_my_users(
    page: int = 1,
    page_size: int = 10,
    # Injection automatique du connecteur pré-configuré avec transfert de l'Authorization Bearer
    connector: PrestdServiceConnector = Depends(get_service_connector(base_url=MICROSERVICE_URL)),
) -> dict[str, Any]:
    """Endpoint métier qui délègue la requête au microservice prestd Swagger."""
    result: PaginatedResponse = (
        await connector.table("users")
        .page(page=page, page_size=page_size)
        .order_by("-id")
        .list()
    )
    return {
        "items": result.data,
        "page": result.page,
        "page_size": result.page_size,
        "total": result.total_rows,
        "total_pages": result.total_pages,
    }


if __name__ == "__main__":
    print("Exemple de connecteur prestd / Swagger prêt.")
    # Pour tester localement si le microservice tourne sur le port 8000 :
    # asyncio.run(demo_async_connector())
