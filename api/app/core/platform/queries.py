"""Read models for the platform (API.md 5): `/me`, `/users`, `/plants`, `/tenant/settings`. Read-only transactions,
explicit columns (never `password_hash`), keyset pagination on the UUIDv7 id (index `(tenant_id, id)`)."""

from uuid import UUID

from sqlalchemy import select

from app.core.errors import BadRequest, NotFound
from app.core.models import Plant, Tenant, User
from app.core.pagination import DEFAULT_LIMIT, decode_cursor, encode_cursor
from app.core.permissions import ROLE_ADMIN, Actor
from app.core.platform.schemas import (
    Me,
    MePlant,
    Page,
    PlantRead,
    SettingsRead,
    TenantSettings,
    UserRead,
)
from app.core.tenancy import actor_tx

SORT_ID = "id"


def _after_id(cursor: str | None) -> UUID | None:
    if cursor is None:
        return None
    keys = decode_cursor(cursor, SORT_ID)
    try:
        return UUID(str(keys[0]))
    except (IndexError, ValueError) as exc:
        raise BadRequest("That page cursor is not valid. Start again from the first page.") from exc


def get_me(actor: Actor) -> Me:
    with actor_tx(actor) as db:
        user = db.execute(
            select(
                User.id, User.email, User.name, User.role, User.can_approve, User.plant_ids
            ).where(User.tenant_id == actor.tenant_id, User.id == actor.user_id)
        ).first()
        if user is None:
            raise NotFound("We could not find your account.")
        plants_query = select(Plant.id, Plant.name, Plant.code, Plant.timezone).where(
            Plant.tenant_id == actor.tenant_id
        )
        if user.role != ROLE_ADMIN:  # Admin sees every plant (A-04); others only their own
            plants_query = plants_query.where(Plant.id.in_(user.plant_ids))
        plants = db.execute(plants_query.order_by(Plant.code, Plant.id)).all()
    return Me(
        id=user.id,
        email=user.email,
        name=user.name,
        role=user.role,
        can_approve=user.can_approve,
        plants=[MePlant(id=p.id, name=p.name, code=p.code, timezone=p.timezone) for p in plants],
    )


def list_users(
    actor: Actor, limit: int = DEFAULT_LIMIT, cursor: str | None = None
) -> Page[UserRead]:
    after = _after_id(cursor)
    query = select(
        User.id,
        User.email,
        User.name,
        User.mobile,
        User.role,
        User.can_approve,
        User.plant_ids,
        User.active,
    ).where(User.tenant_id == actor.tenant_id)
    if after is not None:
        query = query.where(User.id > after)
    with actor_tx(actor) as db:
        rows = db.execute(query.order_by(User.id).limit(limit + 1)).all()
    items = [
        UserRead(
            id=r.id,
            email=r.email,
            name=r.name,
            mobile=r.mobile,
            role=r.role,
            can_approve=r.can_approve,
            plant_ids=list(r.plant_ids),
            active=r.active,
        )
        for r in rows[:limit]
    ]
    more = len(rows) > limit
    return Page[UserRead](
        items=items, next_cursor=encode_cursor([str(items[-1].id)], SORT_ID) if more else None
    )


def list_plants(
    actor: Actor, limit: int = DEFAULT_LIMIT, cursor: str | None = None
) -> Page[PlantRead]:
    after = _after_id(cursor)
    query = select(Plant.id, Plant.name, Plant.code, Plant.address, Plant.timezone).where(
        Plant.tenant_id == actor.tenant_id
    )
    if after is not None:
        query = query.where(Plant.id > after)
    with actor_tx(actor) as db:
        rows = db.execute(query.order_by(Plant.id).limit(limit + 1)).all()
    items = [
        PlantRead(id=r.id, name=r.name, code=r.code, address=r.address, timezone=r.timezone)
        for r in rows[:limit]
    ]
    more = len(rows) > limit
    return Page[PlantRead](
        items=items, next_cursor=encode_cursor([str(items[-1].id)], SORT_ID) if more else None
    )


def get_tenant_settings(actor: Actor) -> SettingsRead:
    with actor_tx(actor) as db:
        stored = db.scalar(select(Tenant.settings).where(Tenant.id == actor.tenant_id))
    if stored is None:
        raise NotFound("We could not find your company.")
    return SettingsRead(settings=TenantSettings.model_validate(stored))
