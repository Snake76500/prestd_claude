"""Exemples avancés avec le QueryBuilder fluide (prestd GET /{db}/{schema}/{table}).

Couvre les fonctionnalités avancées :
- Combinaisons de filtres logiques (Op.in_, Op.like, Op.is_null, .or_())
- Projections (_select), Tris (_order), Group By (_groupby), Distinct (_distinct)
- Comptage (_count, _count_first)
- Recherche vectorielle pgvector (_korder / knn_order)
"""
import asyncio
from prestd_client import PrestdClient, Op


async def main() -> None:
    async with PrestdClient("http://localhost:3000", default_database="mydb") as client:

        # 1. Filtres combinés avec opérateurs Op.*
        # ------------------------------------------
        # SELECT * FROM users WHERE age >= 21 AND role IN ('admin', 'mod') AND deleted_at IS NULL
        results = await (
            client.table("users")
            .gte("age", 21)
            .in_("role", ["admin", "moderator"])
            .is_null("deleted_at")
            .order("-created_at")
            .execute()
        )
        print("Utilisateurs filtrés :", len(results))

        # 2. Recherche textuelle insensible à la casse (LIKE / ILIKE)
        # -----------------------------------------------------------
        # SELECT * FROM articles WHERE title ILIKE '%prestd%'
        articles = await (
            client.table("articles")
            .ilike("title", "%prestd%")
            .execute()
        )
        print("Articles trouvés :", len(articles))

        # 3. Clause OU logique avec .or_()
        # --------------------------------
        # SELECT * FROM articles WHERE (title ILIKE '%prestd%' OR summary ILIKE '%prestd%')
        or_results = await (
            client.table("articles")
            .or_("title=$ilike.%prestd%", "summary=$ilike.%prestd%")
            .execute()
        )
        print("Articles (titre ou résumé) :", len(or_results))

        # 4. Projections et Distinct
        # --------------------------
        # SELECT DISTINCT category FROM products
        categories = await (
            client.table("products")
            .select("category")
            .distinct(True)
            .execute()
        )
        print("Catégories distinctes :", categories)

        # 5. Group By et Comptage
        # -----------------------
        # SELECT count(*) FROM orders GROUP BY status
        order_counts = await (
            client.table("orders")
            .group_by("status")
            .count("id")
            .execute()
        )
        print("Comptage des commandes par statut :", order_counts)

        # 6. Recherche vectorielle KNN (pgvector - prestd >= v2.4.0)
        # ----------------------------------------------------------
        # Tri par similarité cosinus avec un vecteur embedding de dimension 3
        # column: "embedding", metric: "<=>" (cosine distance), vector: [0.1, 0.8, -0.4]
        similar_docs = await (
            client.table("document_embeddings")
            .knn_order("embedding", "<=>", [0.12, 0.85, -0.44])
            .page(1, 5)
            .execute()
        )
        print("Documents les plus proches :", len(similar_docs))


if __name__ == "__main__":
    asyncio.run(main())
