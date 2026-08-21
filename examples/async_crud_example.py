"""Exemple complet d'utilisation asynchrone de PrestdClient.

Couvre l'ensemble des endpoints exposés par le client :
- Découverte et santé : health(), ready(), databases(), schemas(), tables(), describe_table()
- Écriture : insert(), batch_insert()
- Lecture : table() avec QueryBuilder (filtres, tri, pagination, projections)
- Mise à jour : update()
- Suppression : delete()
- Authentification : login(), set_token(), JWTAuth
"""
import asyncio
from prestd_client import PrestdClient, Op, JWTAuth


async def main() -> None:
    base_url = "http://localhost:3000"
    database = "mydb"

    # 1. Initialisation du client (avec auth automatique JWT si activée sur prestd)
    # --------------------------------------------------------------------------
    async with PrestdClient(
        base_url,
        default_database=database,
        default_schema="public",
        # Optionnel : middleware JWT auto-refresh
        # auth=JWTAuth("prest", "prest"),
    ) as client:

        # 2. Authentification explicite ponctuelle (si auth=... non utilisé)
        # ------------------------------------------------------------------
        # token = await client.login("prest", "prest")
        # print(f"Jeton JWT obtenu : {token[:15]}...")
        # Ou attacher un token existant :
        # client.set_token("eyJhbGci...")

        # 3. Vérification de santé et readiness
        # -------------------------------------
        # GET /_health
        health_status = await client.health()
        print("Health status :", health_status)

        # GET /_ready
        ready_status = await client.ready()
        print("Readiness status :", ready_status)

        # 4. Découverte du schéma et métadonnées
        # ---------------------------------------
        # GET /databases
        dbs = await client.databases()
        print(f"Bases de données ({len(dbs)}) :", dbs)

        # GET /schemas
        schemas = await client.schemas()
        print(f"Schémas ({len(schemas)}) :", schemas)

        # GET /tables
        tables = await client.tables()
        print(f"Tables ({len(tables)}) :", tables)

        # GET /show/{database}/{schema}/{table}
        columns = await client.describe_table("users")
        print("Structure de la table 'users' :", columns)

        # 5. Insertion simple et en lot (INSERT)
        # ---------------------------------------
        # Option A : Syntaxe fluide via table("users")
        user_a = await client.table("users").insert({
            "name": "Alice Dupont",
            "email": "alice@example.com",
            "age": 30,
            "role": "admin",
            "active": True,
        })
        print("Utilisateur inséré via table().insert() :", user_a)

        # Option B : Syntaxe directe client.insert("users", ...)
        user_b = await client.insert("users", {
            "name": "David Bowie",
            "email": "david@example.com",
            "age": 50,
            "role": "artist",
            "active": True,
        })
        print("Utilisateur inséré via client.insert() :", user_b)

        # Insertion en lot (batch_insert)
        batch_users = await client.table("users").batch_insert([
            {"name": "Bob Martin", "email": "bob@example.com", "age": 25, "role": "editor", "active": True},
            {"name": "Charlie Durand", "email": "charlie@example.com", "age": 42, "role": "viewer", "active": False},
        ])
        print("Lot d'utilisateurs inséré :", batch_users)

        # 6. Lecture et requêtage fluide (SELECT)
        # ---------------------------------------
        # GET /{db}/{schema}/{table}?active=true&age=$gte.18&_order=-created_at&_page=1&_page_size=10
        users = await (
            client.table("users")
            .eq("active", True)
            .gte("age", 18)
            .order("-created_at")
            .page(page=1, page_size=10)
            .execute()
        )
        print(f"Utilisateurs actifs (page 1) : {len(users)} trouvés")

        # Sélection de colonnes spécifiques (_select)
        names_only = await (
            client.table("users")
            .select("id", "name", "email")
            .eq("role", "admin")
            .execute()
        )
        print("Admins (colonnes restreintes) :", names_only)

        # Récupérer un seul enregistrement (.first())
        first_admin = await client.table("users").eq("role", "admin").first()
        print("Premier admin trouvé :", first_admin)

        # Comptage (_count)
        total_users = await client.table("users").count().execute()
        print("Nombre total d'utilisateurs :", total_users)

        # 7. Mise à jour filtrée (UPDATE / PATCH)
        # ---------------------------------------
        # Option A : Syntaxe fluide via table("users").eq(...).update(...)
        await client.table("users").eq("email", "alice@example.com").update(
            {"active": False, "role": "inactive_admin"}
        )
        print("Alice désactivée via table().eq().update()")

        # Option B : Syntaxe directe client.update("users", data, filters)
        updated = await client.update(
            "users",
            data={"active": False},
            filters={"age": Op.lt(18)},
        )
        print("Utilisateurs mineurs mis à jour :", updated)

        # 8. Suppression filtrée (DELETE)
        # -------------------------------
        # Option A : Syntaxe fluide via table("users").eq(...).delete()
        await client.table("users").eq("email", "charlie@example.com").delete()
        print("Charlie supprimé via table().eq().delete()")

        # Option B : Syntaxe directe client.delete("users", filters)
        deleted = await client.delete(
            "users",
            filters={"age": Op.gte(100)},
        )
        print("Utilisateurs centenaires supprimés :", deleted)


if __name__ == "__main__":
    asyncio.run(main())
