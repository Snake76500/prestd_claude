"""Exemple complet d'utilisation synchrone de SyncPrestdClient.

Idéal pour scripts d'automatisation, notebooks Jupyter, pipelines de batchs.
Couvre tous les endpoints :
- health(), ready()
- databases(), schemas(), tables(), describe_table()
- insert(), batch_insert()
- select()
- update()
- delete()
- login(), set_token()
"""
from prestd_client import SyncPrestdClient, Op


def main() -> None:
    base_url = "http://localhost:3000"
    database = "mydb"

    # 1. Initialisation dans un bloc contextuel synchrone (with)
    # -----------------------------------------------------------
    with SyncPrestdClient(base_url, default_database=database, default_schema="public") as client:

        # 2. Authentification (si prestd a PREST_AUTH_ENABLED=true)
        # ---------------------------------------------------------
        # token = client.login("prest", "prest")
        # Ou : client.set_token("eyJhbGci...")

        # 3. Vérification de santé et readiness
        # -------------------------------------
        print("Health status :", client.health())
        print("Ready status  :", client.ready())

        # 4. Découverte de schéma et métadonnées
        # ---------------------------------------
        print("Databases :", client.databases())
        print("Schemas   :", client.schemas())
        print("Tables    :", client.tables())
        print("Colonnes de 'products' :", client.describe_table("products"))

        # 5. Insertions (INSERT)
        # -----------------------
        # Insertion d'un article
        item = client.insert("products", {
            "sku": "KB-101",
            "name": "Clavier Mécanique",
            "price": 89.99,
            "in_stock": True,
            "category": "peripherals",
        })
        print("Produit inséré :", item)

        # Insertion en lot
        items = client.batch_insert("products", [
            {"sku": "MS-202", "name": "Souris Sans Fil", "price": 49.99, "in_stock": True, "category": "peripherals"},
            {"sku": "MN-303", "name": "Écran 27 pouces", "price": 279.00, "in_stock": False, "category": "displays"},
        ])
        print("Produits insérés en lot :", items)

        # 6. Lecture simple avec select()
        # -------------------------------
        # Tous les périphériques en stock
        in_stock_peripherals = client.select(
            "products",
            category="peripherals",
            in_stock="true",
            order="-price",
        )
        print("Périphériques en stock :", in_stock_peripherals)

        # Avec opérateurs typés Op.*
        expensive_items = client.select(
            "products",
            price=Op.gte(80.00),
            order="price",
            page=1,
            page_size=5,
        )
        print("Produits >= 80€ :", expensive_items)

        # 7. Mise à jour filtrée (UPDATE / PATCH)
        # ---------------------------------------
        client.update(
            "products",
            data={"price": 79.99},
            filters={"sku": "KB-101"},
        )
        print("Prix du clavier mis à jour.")

        # 8. Suppression filtrée (DELETE)
        # -------------------------------
        client.delete(
            "products",
            filters={"sku": "MN-303"},
        )
        print("Écran supprimé.")


if __name__ == "__main__":
    main()
