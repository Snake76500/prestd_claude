Documentation : Utilisation de PrestdClient (client.py)
Le module 

client.py
 implémente PrestdClient, un client HTTP asynchrone moderne basé sur httpx pour interagir avec une instance prestd.

1. Initialisation & Configuration
Signature du constructeur
python
PrestdClient(
    base_url: str,
    *,
    default_database: str | None = None,
    default_schema: str = "public",
    timeout: float = 30.0,
    verify: bool = True,
    transport: httpx.AsyncBaseTransport | None = None,
    auth: BaseAuth | None = None,
    keycloak_token: str | None = None,
    verify_permissions: bool = True,
    admin_roles: Sequence[str] | None = None,
    default_page_size: int | None = None,
    max_page_size: int | None = None,
)
Paramètre	Type	Défaut	Description
base_url	str	Obligatoire	URL de base de l'instance prestd (ex: http://localhost:3000).
default_database	str | None	None	Base de données PostgreSQL ciblée par défaut.
default_schema	str	"public"	Schéma de base par défaut.
timeout	float	30.0	Durée maximale d'attente (secondes) avant timeout.
verify	bool	True	Vérification des certificats SSL/TLS.
auth	BaseAuth | None	None	Stratégie d'authentification (JWTAuth, KeycloakAuth, BasicAuth, etc.).
keycloak_token	str | None	None	Jeton JWT Keycloak direct.
verify_permissions	bool	True	Contrôle local RBAC basé sur les claims JWT avant émission de la requête.
admin_roles	Sequence[str] | None	None	Rôles bénéficiant d'un accès administrateur sans restriction.
default_page_size	int | None	None	Taille de page par défaut injectée si omise.
max_page_size	int | None	None	Limite haute forcée sur _page_size.
2. Cycle de vie & Authentification
Utilisation avec Context Manager Asynchrone (Recommandé)
python
import asyncio
from prestd_client import PrestdClient, JWTAuth
async def main():
    # Avec re-login automatique sur expiration du token (401)
    auth = JWTAuth("prest_user", "prest_password")
    
    async with PrestdClient(
        "http://localhost:3000",
        default_database="mydb",
        auth=auth
    ) as client:
        health = await client.health()
        print(health)
asyncio.run(main())
Méthodes d'authentification manuelles
await client.login(username, password) : Appelle POST /auth pour récupérer et attacher un jeton JWT.
client.set_token(token) : Attache un JWT déjà provisionné (en-tête Authorization: Bearer <token>).
client.set_keycloak_token(token) : Attache un jeton Keycloak et active la validation des rôles RBAC.
client.current_user : Propriété renvoyant le contexte utilisateur (UserContext) extrait du token JWT.
client.has_table_permission(table, action) : Vérifie si le token autorise l'action ("read", "write", "delete").
3. Découverte & Inspection du Schéma
python
# Vérifier la santé du serveur
status = await client.health()   # GET /_health
ready = await client.ready()     # GET /_ready
# Explorer le métamodèle
dbs = await client.databases()   # GET /databases
schemas = await client.schemas() # GET /schemas
tables = await client.tables()   # GET /tables
# Inspecter les colonnes et types d'une table
columns = await client.describe_table("users") # GET /show/mydb/public/users
4. Opérations CRUD Directes
Le client permet d'exécuter des requêtes directes sans passer par le Query Builder :

python
from prestd_client import Op
# 1. Insertion (une ligne ou lot)
new_user = await client.insert("users", {"name": "Alice", "email": "alice@example.com"})
batch_users = await client.batch_insert("users", [
    {"name": "Bob", "email": "bob@example.com"},
    {"name": "Charlie", "email": "charlie@example.com"}
])
# 2. Mise à jour filtrée (filtre obligatoire pour sécurité)
await client.update(
    "users",
    data={"active": False},
    filters={"id": "42"}
)
# Mise à jour avec opérateur
await client.update(
    "orders",
    data={"status": "archived"},
    filters={"created_at": Op.lt("2024-01-01")}
)
# 3. Suppression filtrée (filtre obligatoire pour sécurité)
await client.delete("sessions", filters={"expired_at": Op.lt("2026-01-01")})
5. Utilisation via le Query Builder (client.table(...))
La méthode client.table("nom_table") renvoie une instance de 

QueryBuilder
.

python
# SELECT avec filtres, tri et pagination
users = await (
    client.table("users")
    .select("id", "name", "email", "created_at")
    .eq("active", True)
    .gt("age", 18)
    .order("-created_at")       # Tri descendant (préfixe -)
    .page(page=1, page_size=20)
    .execute()
)
# Récupérer le premier résultat
first_user = await client.table("users").eq("email", "alice@example.com").first()
# Streaming mémoire (parcours page par page automatique)
async for user in client.table("users").stream(batch_size=100):
    print(user["email"])
# Streaming par bloc de pages
async for page_rows in client.table("logs").stream_pages(batch_size=500):
    process_batch(page_rows)
# Opérations d'écriture fluides
await client.table("users").insert({"name": "David", "role": "editor"})
await client.table("users").eq("id", 10).update({"role": "admin"})
await client.table("users").eq("id", 10).delete()
Liste Exhaustive des Opérateurs (Op)
Définis dans 

operators.py
, les opérateurs traduisent les conditions Python en paramètres conformes à la syntaxe prestd (champ=$opérateur.valeur).

Tableau récapitulatif
Opérateur	Méthode Op	Équivalent QueryBuilder	Format prestd	Description
Égalité	Op.eq(v)	.eq(col, v)	col=v	Égalité stricte (=)
Non égal	Op.ne(v)	.ne(col, v)	col=$ne.v	Différent de (!=)
Strictement supérieur	Op.gt(v)	.gt(col, v)	col=$gt.v	Supérieur strict (>)
Supérieur ou égal	Op.gte(v)	.gte(col, v)	col=$gte.v	Supérieur ou égal (>=)
Strictement inférieur	Op.lt(v)	.lt(col, v)	col=$lt.v	Inférieur strict (<)
Inférieur ou égal	Op.lte(v)	.lte(col, v)	col=$lte.v	Inférieur ou égal (<=)
Appartenance	Op.in_(list)	.in_(col, list)	col=$in.v1,v2	Présent dans la liste (IN (...))
Non-appartenance	Op.nin(list)	.nin(col, list)	col=$nin.v1,v2	Absent de la liste (NOT IN (...))
Est nul	Op.is_null()	.is_null(col)	col=$null	Vaut NULL (IS NULL)
N'est pas nul	Op.is_not_null()	.is_not_null(col)	col=$notnull	Différent de NULL (IS NOT NULL)
Vrai	Op.is_true()	.filter(col, Op.is_true())	col=$true	Booléen IS TRUE
Pas vrai	Op.is_not_true()	.filter(col, Op.is_not_true())	col=$nottrue	Booléen IS NOT TRUE
Faux	Op.is_false()	.filter(col, Op.is_false())	col=$false	Booléen IS FALSE
Pas faux	Op.is_not_false()	.filter(col, Op.is_not_false())	col=$notfalse	Booléen IS NOT FALSE
Motif sensible à la casse	Op.like(pattern)	.like(col, pattern)	col=$like.pattern	Expression SQL LIKE
Motif insensible à la casse	Op.ilike(pattern)	.ilike(col, pattern)	col=$ilike.pattern	Expression SQL ILIKE
Négation LIKE	Op.nlike(pattern)	.filter(col, Op.nlike(p))	col=$nlike.pattern	Expression SQL NOT LIKE
Négation ILIKE	Op.nilike(pattern)	.filter(col, Op.nilike(p))	col=$nilike.pattern	Expression SQL NOT ILIKE
Ancêtre ltree	Op.ltree_ancestor(path)	.filter(col, Op.ltree_ancestor(p))	col=$ltreelanc.path	Extension PostgreSQL ltree @>
Descendant ltree	Op.ltree_descendant(path)	.filter(col, Op.ltree_descendant(p))	col=$ltreerdesc.path	Extension PostgreSQL ltree <@
Match ltree (lquery)	Op.ltree_match(lquery)	.filter(col, Op.ltree_match(q))	col=$ltreematch.q	Extension PostgreSQL ltree ~
Match ltree texte	Op.ltree_match_text(txt)	.filter(col, Op.ltree_match_text(t))	col=$ltreematchtxt.t	Extension PostgreSQL ltree ?
Exemples Détaillés par Opérateur
1. Comparaisons de base & Nombres
python
from prestd_client import Op
# Égalité & Différence
await client.table("users").eq("status", "active").execute()
await client.table("users").ne("status", "deleted").execute()
# Bornes & Intervalles
await client.table("products").gt("price", 100).execute()
await client.table("products").gte("stock", 10).execute()
await client.table("products").lt("price", 500).execute()
await client.table("products").lte("discount", 0.5).execute()
# Utilisation directe de Op avec .filter() ou client.update()
await client.table("products").filter("price", Op.gt(100)).execute()
await client.update("products", data={"promo": True}, filters={"price": Op.gte(100)})
2. Listes et Ensembles (IN / NOT IN)
python
# In
await client.table("users").in_("role", ["admin", "moderator", "support"]).execute()
# Not In
await client.table("orders").nin("status", ["canceled", "refunded"]).execute()
# Via Op
await client.table("users").filter("id", Op.in_([1, 2, 3, 5, 8])).execute()
3. Gestion des Valeurs Nulles
python
# Vérifier si NULL
await client.table("users").is_null("deleted_at").execute()
# Vérifier si NON NULL
await client.table("orders").is_not_null("shipped_at").execute()
# Via Op
await client.delete("tokens", filters={"revoked_at": Op.is_not_null()})
4. Booléens Tri-valués (PostgreSQL IS TRUE / FALSE / UNKNOWN)
python
# Vrai / Faux
await client.table("tasks").filter("is_done", Op.is_true()).execute()
await client.table("tasks").filter("is_done", Op.is_false()).execute()
# Not True / Not False (gère aussi le cas où la valeur est NULL)
await client.table("tasks").filter("archived", Op.is_not_true()).execute()
await client.table("tasks").filter("flagged", Op.is_not_false()).execute()
5. Recherche Textuelle (Pattern Matching)
python
# ILIKE (insensible à la casse)
await client.table("articles").ilike("title", "%python%").execute()
# LIKE (sensible à la casse)
await client.table("serials").like("code", "SN-%").execute()
# Négations NOT LIKE / NOT ILIKE
await client.table("logs").filter("message", Op.nlike("%DEBUG%")).execute()
await client.table("emails").filter("address", Op.nilike("%@spam.com")).execute()
6. Arborescences PostgreSQL (ltree)
python
# Ancêtre (@>) : vérifie si le champ contient le chemin en tant qu'ancêtre
await client.table("categories").filter("path", Op.ltree_ancestor("Top.Science")).execute()
# Descendant (<@) : vérifie si le chemin est descendant
await client.table("categories").filter("path", Op.ltree_descendant("Top.Science.Astronomy")).execute()
# Match de pattern lquery (~)
await client.table("categories").filter("path", Op.ltree_match("Top.*.Astronomy")).execute()
# Match textuel ltxtquery (?)
await client.table("categories").filter("path", Op.ltree_match_text("Science & !Fiction")).execute()
7. Conditions Logiques OR (_or)
Prestd permet de combiner des clauses avec l'opérateur || :

python
# Recherche multi-colonnes avec OR
await (
    client.table("articles")
    .or_("title=$ilike.%search%", "content=$ilike.%search%")
    .execute()
)
Fonctions d'Agrégation (Agg)
La classe 

Agg
 fournit les agrégats SQL supportés par prestd :

Méthode	SQL équivalent	Exemple
Agg.sum(col)	SUM(col)	Agg.sum("total_amount") -> "sum:total_amount"
Agg.avg(col)	AVG(col)	Agg.avg("score") -> "avg:score"
Agg.max(col)	MAX(col)	Agg.max("price") -> "max:price"
Agg.min(col)	MIN(col)	Agg.min("price") -> "min:price"
Agg.stddev(col)	STDDEV(col)	Agg.stddev("latency") -> "stddev:latency"
Agg.variance(col)	VARIANCE(col)	Agg.variance("temperature") -> "variance:temperature"
Exemple avec Group By
python
from prestd_client import Agg
# Total des ventes et panier moyen groupés par statut
stats = await (
    client.table("orders")
    .select("status", Agg.sum("amount"), Agg.avg("amount"), Agg.max("amount"))
    .group_by("status")
    .execute()
)
Tri Vectoriel pgvector (knn_order)
Si l'extension PostgreSQL pgvector est activée et que prestd est en version >= 2.4.0 :

python
# Recherche du plus proche voisin (K-Nearest Neighbors)
embedding = [0.024, -0.12, 0.45, 0.89]
results = await (
    client.table("document_chunks")
    .knn_order("embedding", "<->", embedding)  # Distance L2 / Euclidienne (<->), Cosinus (<=>), ou Produit scalaire (<#>)
    .page(1, 5)
    .execute()
)
Gestion des Erreurs et Exceptions
Toutes les erreurs retournées par l'API prestd sont converties en exceptions Python typées (

exceptions.py
) :

python
from prestd_client import (
    PrestdError,
    PrestdConnectionError,  # Problème réseau ou timeout
    PrestdAuthError,        # 401 Unauthorized
    PrestdPermissionError,  # 403 Forbidden
    PrestdNotFoundError,    # 404 Not Found
    PrestdValidationError,  # 400 / 422 Bad Request
    PrestdServerError,      # 500+ Internal Error
)
try:
    await client.table("restricted_data").execute()
except PrestdPermissionError as e:
    print(f"Action interdite : {e.message}")
except PrestdNotFoundError:
    print("Table ou ressource introuvable")
except PrestdConnectionError as e:
    print(f"Serveur prestd inaccessible : {e}")
except PrestdError as e:
    print(f"Erreur prestd HTTP {e.status_code}: {e.message}")
14:36
