"""Configuration du microservice, chargée depuis les variables d'environnement / .env."""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # -- connexion à prestd ------------------------------------------------
    prestd_base_url: str = "http://localhost:3000"
    prestd_database: str = "prest"
    prestd_schema: str = "public"

    # Optionnel : se logger au démarrage et réutiliser le JWT pour tous les
    # appels forwardés. Laisser vide si PREST_AUTH_ENABLED=false sur prestd.
    prestd_username: str | None = None
    prestd_password: str | None = None
    # Ou fournir directement un token statique déjà généré.
    prestd_static_token: str | None = None

    prestd_timeout_seconds: float = 30.0

    # -- auth propre à ce microservice --------------------------------------
    # Si définie, chaque requête doit fournir `X-API-Key: <valeur>`.
    # Laisser vide pour désactiver (ex: microservice derrière un réseau
    # interne de confiance / reverse-proxy Caddy).
    service_api_key: str | None = None

    # -- auth Keycloak & permissions ----------------------------------------
    keycloak_enabled: bool = True
    keycloak_server_url: str | None = None
    keycloak_realm: str = "master"
    keycloak_client_id: str | None = None
    keycloak_public_key: str | None = None  # Clé publique PEM / RSA ou secret HMAC
    keycloak_audience: str | None = None
    keycloak_admin_roles: list[str] = ["admin", "realm-admin", "superuser"]
    keycloak_algorithms: list[str] = ["RS256", "HS256"]

    # -- divers ---------------------------------------------------------------
    cors_allow_origins: list[str] = ["*"]
    log_level: str = "INFO"


settings = Settings()
