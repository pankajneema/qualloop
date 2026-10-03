"""Route registration helpers.

Module routers carry the full `/api/v1/...` path (`api_router`) and are attached to the app with `mount`, which adds their
routes to `app.routes` one by one. FastAPI's `include_router` is lazy in current releases (`app.routes` then holds opaque
include objects), and the route-table guards (no PUT/PATCH/DELETE, every POST is a registered command, INV-PLT-06/10)
need to read concrete paths and methods from `app.routes`.
"""

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.routing import APIRoute

from app.core.errors import PROBLEM_RESPONSES

API_PREFIX = "/api/v1"


def api_router(prefix: str = "", **kwargs: Any) -> APIRouter:
    """An `APIRouter` whose routes live under `/api/v1` + `prefix`."""
    return APIRouter(prefix=API_PREFIX + prefix, responses=PROBLEM_RESPONSES, **kwargs)


def mount(app: FastAPI, *routers: APIRouter) -> None:
    for router in routers:
        for route in router.routes:
            if not isinstance(route, APIRoute):
                raise TypeError(
                    f"mount() takes routers with plain routes only, got {type(route).__name__}"
                )
            app.router.routes.append(route)
