"""Exemple d'utilisation de la librairie prestd_connector."""
import asyncio
import os
from prestd_connector import PrestdClient, SyncPrestdClient

# Optionnel : Définition des variables d'environnement
os.environ.setdefault("PRESTD_URL", "http://localhost:3000")
os.environ.setdefault("PRESTD_DATABASE", "prest")
os.environ.setdefault("PRESTD_SCHEMA", "public")


async def async_demo():
    print("--- Démo Asynchrone ---")
    # Instanciation automatique sans arguments (lit os.environ)
    async with PrestdClient() as client:
        # 1. Santé
        health = await client.health()
        print("Health status:", health)

        # 2. Métadonnées
        tables = await client.get_tables()
        print("Tables disponibles:", tables)

        # 3. Requête table avec filtres et pagination
        # Toutes les méthodes natives de prestd_client sont directement disponibles !
        try:
            users = (
                await client.table("users")
                .select("id", "name", "email")
                .eq("active", True)
                .order("-created_at")
                .page(1)
                .page_size(10)
                .execute()
            )
            print("Users récupérés:", users)
        except Exception as e:
            print("Erreur requête table:", e)


def sync_demo():
    print("\n--- Démo Synchrone ---")
    with SyncPrestdClient() as client:
        health = client.health()
        print("Health status (sync):", health)


if __name__ == "__main__":
    asyncio.run(async_demo())
    sync_demo()
