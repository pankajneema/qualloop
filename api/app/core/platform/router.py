"""HTTP routes of the platform module: commands are POST, queries are GET (API.md 1.1, 3.1, 5)."""

from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from fastapi.responses import JSONResponse

from app.core.auth.deps import require
from app.core.commands.http import execute, idempotency_key_header
from app.core.pagination import DEFAULT_LIMIT, CursorParam, LimitParam
from app.core.permissions import ADMIN, ANY_USER, Actor
from app.core.platform import commands, queries
from app.core.platform.schemas import (
    Me,
    Page,
    PlantCreate,
    PlantRead,
    PlantUpdate,
    PlantUpdateInput,
    SettingsRead,
    SettingsUpdate,
    UserCreate,
    UserDeactivate,
    UserDeactivateInput,
    UserRead,
    UserUpdate,
    UserUpdateInput,
)
from app.core.routing import api_router

router = api_router(tags=["platform"])

AdminActor = Annotated[Actor, Depends(require(ADMIN))]
AdminReader = Annotated[Actor, Depends(require(ADMIN, command=False))]
AnyActor = Annotated[Actor, Depends(require(ANY_USER, command=False))]
IdempotencyKey = Annotated[str | None, Depends(idempotency_key_header)]


# ------------------------------------------------------------------------------------------------ commands
@router.post("/users", response_model=UserRead, status_code=201)
def create_user(
    body: UserCreate, request: Request, actor: AdminActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(commands.CREATE_USER, body, request=request, actor=actor, idempotency_key=key)


@router.post("/users/{id}/update", response_model=UserRead)
def update_user(
    id: UUID, body: UserUpdate, request: Request, actor: AdminActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_USER,
        UserUpdateInput(user_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/users/{id}/deactivate", response_model=UserRead)
def deactivate_user(
    id: UUID, body: UserDeactivate, request: Request, actor: AdminActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.DEACTIVATE_USER,
        UserDeactivateInput(user_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/plants", response_model=PlantRead, status_code=201)
def create_plant(
    body: PlantCreate, request: Request, actor: AdminActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(commands.CREATE_PLANT, body, request=request, actor=actor, idempotency_key=key)


@router.post("/plants/{id}/update", response_model=PlantRead)
def update_plant(
    id: UUID, body: PlantUpdate, request: Request, actor: AdminActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_PLANT,
        PlantUpdateInput(plant_id=id, body=body),
        request=request,
        actor=actor,
        idempotency_key=key,
    )


@router.post("/tenant/settings/update", response_model=SettingsRead)
def update_tenant_settings(
    body: SettingsUpdate, request: Request, actor: AdminActor, key: IdempotencyKey
) -> JSONResponse:
    return execute(
        commands.UPDATE_SETTINGS, body, request=request, actor=actor, idempotency_key=key
    )


# -------------------------------------------------------------------------------------------------- queries
@router.get("/me", response_model=Me)
def me(actor: AnyActor) -> Me:
    return queries.get_me(actor)


@router.get("/users", response_model=Page[UserRead])
def users(
    actor: AdminReader, limit: LimitParam = DEFAULT_LIMIT, cursor: CursorParam = None
) -> Page[UserRead]:
    return queries.list_users(actor, limit, cursor)


@router.get("/plants", response_model=Page[PlantRead])
def plants(
    actor: AnyActor, limit: LimitParam = DEFAULT_LIMIT, cursor: CursorParam = None
) -> Page[PlantRead]:
    return queries.list_plants(actor, limit, cursor)


@router.get("/tenant/settings", response_model=SettingsRead)
def tenant_settings(actor: AnyActor) -> SettingsRead:
    return queries.get_tenant_settings(actor)
