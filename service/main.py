"""Microservice FastAPI en façade devant un serveur prestd.

Apporte par rapport à prestd brut :
- sa propre auth par API key (indépendante du JWT de prestd)
- authentification vers prestd via middleware (JWTAuth) : login paresseux et
  re-login automatique sur 401, sans dépendre d'un login manuel au démarrage
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
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, JSONResponse

from prestd_client import BaseAuth, JWTAuth, PrestdClient, PrestdError, StaticTokenAuth

from .config import settings
from .routers import health, meta, records
from .security import KeycloakPermissionMiddleware

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger("prestd_service")


def _build_auth() -> BaseAuth | None:
    """Choisit la stratégie d'authentification vers prestd à partir de la config.

    - PRESTD_STATIC_TOKEN si fourni : token déjà généré, pas de rafraîchissement.
    - PRESTD_USERNAME/PASSWORD sinon : JWTAuth, login paresseux au premier
      appel et re-login automatique sur 401 (token expiré).
    - Ni l'un ni l'autre : pas d'auth (prestd tourne sans PREST_AUTH_ENABLED).
    """
    if settings.prestd_static_token:
        return StaticTokenAuth(settings.prestd_static_token)
    if settings.prestd_username and settings.prestd_password:
        return JWTAuth(settings.prestd_username, settings.prestd_password)
    return None


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = PrestdClient(
        settings.prestd_base_url,
        default_database=settings.prestd_database,
        default_schema=settings.prestd_schema,
        timeout=settings.prestd_timeout_seconds,
        auth=_build_auth(),
    )
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
        docs_url=None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(KeycloakPermissionMiddleware)

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

    @app.get("/docs", include_in_schema=False)
    async def custom_swagger_ui_html() -> HTMLResponse:
        res = get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title=f"{app.title} - Swagger UI",
        )
        html = res.body.decode("utf-8")
        js_hook = """<script>
if (typeof ui !== 'undefined' && ui.getConfigs) {
    const origInterceptor = ui.getConfigs().requestInterceptor;
    ui.getConfigs().requestInterceptor = (req) => {
        if (req.url && req.url.indexOf('filter') !== -1) {
            try {
                const isAbsolute = req.url.startsWith('http://') || req.url.startsWith('https://');
                const urlObj = new URL(req.url, window.location.origin);
                const params = new URLSearchParams(urlObj.search);
                const newParams = new URLSearchParams();
                for (const [rawKey, rawVal] of params.entries()) {
                    const key = decodeURIComponent(rawKey);
                    const val = decodeURIComponent(rawVal);
                    if (key === 'filter' || key.startsWith('filter[') || key.startsWith('filter%')) {
                        if (val.indexOf('=') !== -1) {
                            const idx = val.indexOf('=');
                            newParams.append(val.substring(0, idx).trim(), val.substring(idx + 1).trim());
                        } else if (val.indexOf(':') !== -1) {
                            const parts = val.split(':');
                            if (parts.length === 3) {
                                const op = parts[1].startsWith('$') ? parts[1] : '$' + parts[1];
                                newParams.append(parts[0].trim(), op + '.' + parts[2].trim());
                            } else {
                                newParams.append(parts[0].trim(), parts[1].trim());
                            }
                        } else if (val) {
                            newParams.append(val, '');
                        }
                    } else {
                        newParams.append(key, val);
                    }
                }
                urlObj.search = newParams.toString();
                req.url = isAbsolute ? urlObj.toString() : (urlObj.pathname + (urlObj.search ? urlObj.search : ''));
            } catch (e) {
                console.error("Swagger requestInterceptor error:", e);
            }
        }
        return origInterceptor ? origInterceptor(req) : req;
    };
}
</script>
</body>"""
        return HTMLResponse(content=html.replace("</body>", js_hook))

    app.include_router(health.router)
    app.include_router(meta.router)
    app.include_router(records.router)
    return app


app = create_app()
