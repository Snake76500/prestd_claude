"""Microservice FastAPI en façade devant un serveur prestd.

Apporte par rapport à prestd brut :
- sa propre auth par API key (indépendante du JWT de prestd)
- une gestion d'erreurs structurée (PrestdError / ValueError -> HTTP propre)
- des endpoints /healthz, /readyz, /meta/*
- un point d'extension unique pour ajouter rate limiting, cache, logique
  métier, sans toucher au reste de l'infra
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from prestd_client import PrestdClient, PrestdError

from .config import settings
from .routers import health, meta, records

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("prestd_service")


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = PrestdClient(
        settings.prestd_base_url,
        default_database=settings.prestd_database,
        default_schema=settings.prestd_schema,
        timeout=settings.prestd_timeout_seconds,
    )
    if settings.prestd_static_token:
        client.set_token(settings.prestd_static_token)
    elif settings.prestd_username and settings.prestd_password:
        try:
            await client.login(settings.prestd_username, settings.prestd_password)
            logger.info("Connecté à prestd en tant que %s", settings.prestd_username)
        except PrestdError as exc:
            logger.warning("Login prestd impossible au démarrage : %s", exc)

    app.state.prestd_client = client
    try:
        yield
    finally:
        await client.close()


def create_app() -> FastAPI:
    app = FastAPI(
        title="prestd microservice",
        description="Façade FastAPI Pythonique au-dessus d'un serveur prestd (PostgreSQL REST).",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(PrestdError)
    async def prestd_error_handler(request: Request, exc: PrestdError) -> JSONResponse:
        status_code = exc.status_code or 502
        return JSONResponse(
            status_code=status_code,
            content={"error": exc.message, "prestd_status": exc.status_code},
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"error": str(exc)})

    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(records.router)
    return app


app = create_app()
