"""Composes module routers into the app under /api/v1."""

from fastapi import FastAPI

from app.core.auth.router import router as auth_router
from app.core.files.router import router as files_router
from app.core.platform import commands as _platform_commands  # noqa: F401  (registers the commands)
from app.core.platform.router import router as platform_router
from app.core.routing import mount


def mount_api(app: FastAPI) -> None:
    mount(app, auth_router, platform_router, files_router)
