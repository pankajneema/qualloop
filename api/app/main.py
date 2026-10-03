"""App factory: uvicorn app.main:create_app --factory."""

from fastapi import FastAPI

from app.api.middleware import BodySizeLimitMiddleware, RequestIdMiddleware
from app.api.router import mount_api
from app.core import health
from app.core.config import get_settings
from app.core.errors import register_error_handlers
from app.core.logging import configure_logging
from app.core.telemetry import init_telemetry, instrument_app, instrument_engine, instrument_redis


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
    register_error_handlers(app)
    # Added last = outermost: the request id exists before anything else can fail or log.
    app.add_middleware(BodySizeLimitMiddleware)
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router)
    mount_api(app)
    if init_telemetry(settings):
        from app.core.db import get_engine

        instrument_app(app)
        instrument_engine(get_engine())
        instrument_redis()
    return app
