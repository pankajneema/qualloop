"""App factory: uvicorn app.main:create_app --factory."""

from fastapi import FastAPI

from app.api.middleware import RequestIdMiddleware
from app.api.router import api_v1
from app.core import health
from app.core.config import get_settings
from app.core.logging import configure_logging


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.env)
    local = settings.env == "local"
    app = FastAPI(
        title="QualLoop API",
        version=settings.version,
        # API docs and the OpenAPI schema are exposed only in local development.
        openapi_url="/openapi.json" if local else None,
        docs_url="/docs" if local else None,
        redoc_url=None,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    app.include_router(api_v1)
    return app
