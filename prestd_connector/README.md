# prestd_connector

Connecteur Python léger pour consommer les endpoints **prestd** en réutilisant directement `prestd_client.PrestdClient`.

## Fonctionnalités

- **Zéro duplication** : Hérite directement de `PrestdClient` (toutes les méthodes `.table()`, `.insert()`, `.get_tables()`, etc. sont disponibles).
- **Configuration automatique** : Résout l'URL, la base de données et l'authentification depuis les variables d'environnement (`PRESTD_URL`, `PRESTD_DATABASE`, `PRESTD_TOKEN`, `KEYCLOAK_*`).
- **Support FastAPI** : Dépendance prête à l'emploi `get_prestd_client_dependency` avec transmission transparente du Bearer token.
- **Versions Async et Sync** : `PrestdClient` et `SyncPrestdClient`.

## Variables d'environnement supportées

| Variable | Description | Défaut |
| :--- | :--- | :--- |
| `PRESTD_URL` / `PRESTD_BASE_URL` | URL du serveur prestd | `http://localhost:3000` |
| `PRESTD_DATABASE` / `PRESTD_DB` | Base de données par défaut | `None` |
| `PRESTD_SCHEMA` | Schéma par défaut | `public` |
| `PRESTD_TOKEN` | Token Bearer statique | `None` |
| `PRESTD_USERNAME` / `PRESTD_PASSWORD` | Identifiants JWT prestd ou Keycloak | `None` |
| `KEYCLOAK_SERVER_URL` | URL du serveur Keycloak (active l'auth Keycloak) | `None` |
| `KEYCLOAK_REALM` | Realm Keycloak | `master` |
| `KEYCLOAK_CLIENT_ID` | Client ID Keycloak | `prestd` |

## Utilisation

```python
from prestd_connector import PrestdClient

# Instanciation automatique via variables d'environnement
async with PrestdClient() as client:
    # Query builder natif de prestd_client
    users = await (
        client.table("users")
        .select("id", "name")
        .eq("status", "active")
        .order("-created_at")
        .execute()
    )
    
    # Insertion
    await client.insert("users", {"name": "Alice", "status": "active"})
```
