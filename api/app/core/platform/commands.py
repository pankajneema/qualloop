"""Platform commands (API.md 3.1): users, plants, tenant settings. Each is a registered `Command`; the HTTP routes are
in `router.py`. Handlers lock, validate and mutate; `run_command` writes the audit row and the outbox event."""

from typing import Any
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.auth import sessions
from app.core.commands.base import Command, CommandContext, Outcome, register
from app.core.commands.state_machine import StateMachine
from app.core.errors import Conflict, InvariantViolation, NotFound, ValidationFailed, field_error
from app.core.ids import new_id
from app.core.logging import mask_mobile
from app.core.models import Plant, Tenant, User
from app.core.permissions import ADMIN
from app.core.platform.schemas import (
    PlantCreate,
    PlantRead,
    PlantUpdate,
    PlantUpdateInput,
    SettingsRead,
    SettingsUpdate,
    TenantSettings,
    UserCreate,
    UserDeactivateInput,
    UserRead,
    UserUpdateInput,
)
from app.core.redis_client import get_redis
from app.core.timeutils import is_valid_timezone

USER_STATES = StateMachine("user", {("active", "deactivate"): "inactive"})


# ------------------------------------------------------------------------------------------------ read models
def user_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        email=user.email,
        name=user.name,
        mobile=user.mobile,
        role=user.role,
        can_approve=user.can_approve,
        plant_ids=list(user.plant_ids),
        active=user.active,
    )


def plant_read(plant: Plant) -> PlantRead:
    return PlantRead(
        id=plant.id,
        name=plant.name,
        code=plant.code,
        address=plant.address,
        timezone=plant.timezone,
    )


def user_audit(user: UserRead) -> dict[str, Any]:
    """The audit snapshot of a user: the read model with the mobile number masked (ADR-019, no PII in append-only logs)."""
    snapshot = user.model_dump(mode="json")
    if snapshot["mobile"]:
        snapshot["mobile"] = mask_mobile(snapshot["mobile"])
    return snapshot


def settings_of(tenant: Tenant) -> TenantSettings:
    """Stored settings merged over the blueprint defaults (a new tenant stores `{}`)."""
    return TenantSettings.model_validate(tenant.settings or {})


# --------------------------------------------------------------------------------------------------- helpers
def _plants_exist(session: Session, tenant_id: UUID, plant_ids: list[UUID]) -> None:
    if not plant_ids:
        return
    wanted = set(plant_ids)
    found = set(
        session.scalars(select(Plant.id).where(Plant.tenant_id == tenant_id, Plant.id.in_(wanted)))
    )
    if found != wanted:
        raise ValidationFailed(
            "Some plants do not exist.",
            errors=[
                field_error(
                    "plant_ids", "unknown_plant", "Choose plants that belong to your company."
                )
            ],
        )


def _check_timezone(session: Session, timezone: str) -> None:
    known = session.execute(
        text("SELECT 1 FROM pg_timezone_names WHERE name = :name"), {"name": timezone}
    ).first()
    if known is None or not is_valid_timezone(timezone):
        raise ValidationFailed(
            "That timezone is not recognised.",
            errors=[
                field_error(
                    "timezone", "unknown_timezone", "Use an IANA name such as Asia/Kolkata."
                )
            ],
        )


def _lock_user(ctx: CommandContext, user_id: UUID) -> User:
    user = ctx.session.execute(
        select(User)
        .where(User.tenant_id == ctx.actor.tenant_id, User.id == user_id)
        .with_for_update()
    ).scalar_one_or_none()
    if user is None:
        raise NotFound("We could not find that user.")
    return user


def _lock_plant(ctx: CommandContext, plant_id: UUID) -> Plant:
    plant = ctx.session.execute(
        select(Plant)
        .where(Plant.tenant_id == ctx.actor.tenant_id, Plant.id == plant_id)
        .with_for_update()
    ).scalar_one_or_none()
    if plant is None:
        raise NotFound("We could not find that plant.")
    return plant


_NOTHING_TO_CHANGE = ValidationFailed(
    "There is nothing to change.", errors=[field_error("body", "empty", "Send at least one field.")]
)


def _changes(requested: dict[str, Any], *, clearable: set[str]) -> dict[str, Any]:
    """Fields to write: an explicit null clears only nullable columns; for required columns it means "leave as is"."""
    return {k: v for k, v in requested.items() if v is not None or k in clearable}


def _keep_one_active_admin(ctx: CommandContext, user: User) -> None:
    """Refuse to remove the company's last active admin (nobody could then manage users, plants or settings).

    SPEC-GAP: A-98 - the blueprint does not say; the conservative choice is to prevent the lock-out. The other admins are
    locked in id order so two admins cannot demote each other at the same moment."""
    other = ctx.session.scalars(
        select(User.id)
        .where(
            User.tenant_id == ctx.actor.tenant_id,
            User.role == "admin",
            User.active.is_(True),
            User.id != user.id,
        )
        .order_by(User.id)
        .with_for_update()
    ).first()
    if other is None:
        raise InvariantViolation(
            "A company needs at least one active admin. Make someone else an admin first.",
            errors=[field_error("role", "last_admin", "This is the only active admin.")],
        )


def _require_reason(reason: str | None, why: str) -> str:
    if not reason:
        raise ValidationFailed(
            "A reason is needed for this change.",
            errors=[field_error("reason", "required", f"Give a reason: {why}.")],
        )
    return reason


# ------------------------------------------------------------------------------------------------- users
def _create_user(ctx: CommandContext, data: UserCreate) -> Outcome[UserRead]:
    session, actor = ctx.session, ctx.actor
    # Email is unique across all tenants (A-03): look it up through the definer function, which sees every tenant.
    taken = session.execute(
        text("SELECT 1 FROM app_resolve_login(:email)"), {"email": data.email}
    ).first()
    if taken is not None:
        raise Conflict(
            "A user with this email already exists.",
            errors=[field_error("email", "duplicate", "This email is already in use.")],
        )
    _plants_exist(session, actor.tenant_id, data.plant_ids)
    user = User(
        id=new_id(),
        tenant_id=actor.tenant_id,
        email=data.email,
        name=data.name,
        mobile=data.mobile,
        role=data.role,
        can_approve=data.can_approve,
        plant_ids=list(data.plant_ids),
        active=True,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(user)
    session.flush()
    read = user_read(user)
    return Outcome(
        response=read,
        object_type="user",
        object_id=user.id,
        action="user.create",
        event_type="USER_CREATED",
        after=user_audit(read),
        payload={"user_id": str(user.id)},
        status_code=201,
    )


def _update_user(ctx: CommandContext, data: UserUpdateInput) -> Outcome[UserRead]:
    session, actor, body = ctx.session, ctx.actor, data.body
    user = _lock_user(ctx, data.user_id)
    before = user_read(user)
    changes = _changes(
        body.model_dump(exclude_unset=True, exclude={"reason"}), clearable={"mobile"}
    )
    if not changes:
        raise _NOTHING_TO_CHANGE
    if (body.role is not None and body.role != user.role) or (
        body.can_approve is not None and body.can_approve != user.can_approve
    ):
        _require_reason(body.reason, "role and approval rights decide who can do what")
    if body.plant_ids is not None:
        _plants_exist(session, actor.tenant_id, body.plant_ids)
    if user.role == "admin" and user.active and body.role not in (None, "admin"):
        _keep_one_active_admin(ctx, user)
    for field_name, value in changes.items():
        setattr(user, field_name, value)
    user.updated_by = actor.user_id
    session.flush()
    after = user_read(user)
    return Outcome(
        response=after,
        object_type="user",
        object_id=user.id,
        action="user.update",
        event_type="USER_UPDATED",
        before=user_audit(before),
        after=user_audit(after),
        reason=body.reason,
        payload={"user_id": str(user.id)},
    )


def _deactivate_user(ctx: CommandContext, data: UserDeactivateInput) -> Outcome[UserRead]:
    user = _lock_user(ctx, data.user_id)
    USER_STATES.apply("active" if user.active else "inactive", "deactivate")
    if user.role == "admin":
        _keep_one_active_admin(ctx, user)
    before = user_read(user)
    user.active = False
    user.updated_by = ctx.actor.user_id
    ctx.session.flush()
    after = user_read(user)
    user_id = user.id
    return Outcome(
        response=after,
        object_type="user",
        object_id=user_id,
        action="user.deactivate",
        event_type="USER_DEACTIVATED",
        before=user_audit(before),
        after=user_audit(after),
        reason=data.body.reason,
        payload={"user_id": str(user_id)},
        # Sessions end only once the deactivation has committed (and the `active` flag is re-checked on every request).
        after_commit=(lambda: _end_sessions(user_id),),
    )


def _end_sessions(user_id: UUID) -> None:
    sessions.delete_user_sessions(get_redis(), user_id)


# ------------------------------------------------------------------------------------------------ plants
def _create_plant(ctx: CommandContext, data: PlantCreate) -> Outcome[PlantRead]:
    session, actor = ctx.session, ctx.actor
    _check_timezone(session, data.timezone)
    duplicate = session.scalar(
        select(Plant.id).where(Plant.tenant_id == actor.tenant_id, Plant.code == data.code)
    )
    if duplicate is not None:
        raise Conflict(
            "A plant with this code already exists.",
            errors=[
                field_error("code", "duplicate", "Plant codes must be unique in your company.")
            ],
        )
    plant = Plant(
        id=new_id(),
        tenant_id=actor.tenant_id,
        name=data.name,
        code=data.code,
        address=data.address,
        timezone=data.timezone,
        created_by=actor.user_id,
        updated_by=actor.user_id,
    )
    session.add(plant)
    session.flush()
    read = plant_read(plant)
    return Outcome(
        response=read,
        object_type="plant",
        object_id=plant.id,
        action="plant.create",
        event_type="PLANT_CREATED",
        after=read.model_dump(mode="json"),
        payload={"plant_id": str(plant.id)},
        status_code=201,
    )


def _update_plant(ctx: CommandContext, data: PlantUpdateInput) -> Outcome[PlantRead]:
    body: PlantUpdate = data.body
    plant = _lock_plant(ctx, data.plant_id)
    before = plant_read(plant)
    changes = _changes(
        body.model_dump(exclude_unset=True, exclude={"reason"}), clearable={"address"}
    )
    if not changes:
        raise _NOTHING_TO_CHANGE
    if body.timezone is not None:
        _check_timezone(ctx.session, body.timezone)
    for field_name, value in changes.items():
        setattr(plant, field_name, value)
    plant.updated_by = ctx.actor.user_id
    ctx.session.flush()
    after = plant_read(plant)
    return Outcome(
        response=after,
        object_type="plant",
        object_id=plant.id,
        action="plant.update",
        event_type="PLANT_UPDATED",
        before=before.model_dump(mode="json"),
        after=after.model_dump(mode="json"),
        reason=body.reason,
        payload={"plant_id": str(plant.id)},
    )


# ------------------------------------------------------------------------------------------ tenant settings
def _update_settings(ctx: CommandContext, data: SettingsUpdate) -> Outcome[SettingsRead]:
    tenant = ctx.session.execute(
        select(Tenant).where(Tenant.id == ctx.actor.tenant_id).with_for_update()
    ).scalar_one_or_none()
    if tenant is None:
        raise NotFound("We could not find your company.")
    before = settings_of(tenant)
    tenant.settings = data.settings.model_dump(mode="json")
    tenant.updated_by = ctx.actor.user_id
    ctx.session.flush()
    return Outcome(
        response=SettingsRead(settings=data.settings),
        object_type="tenant",
        object_id=tenant.id,
        action="tenant.update_settings",
        event_type="TENANT_SETTINGS_UPDATED",
        before={"settings": before.model_dump(mode="json")},
        after={"settings": data.settings.model_dump(mode="json")},
        reason=data.reason,
        payload={"tenant_id": str(tenant.id)},
    )


# ------------------------------------------------------------------------------------------------ registry
CREATE_USER = register(Command("users.create", "/users", ADMIN, _create_user))
UPDATE_USER = register(Command("users.update", "/users/{id}/update", ADMIN, _update_user))
DEACTIVATE_USER = register(
    Command("users.deactivate", "/users/{id}/deactivate", ADMIN, _deactivate_user)
)
CREATE_PLANT = register(Command("plants.create", "/plants", ADMIN, _create_plant))
UPDATE_PLANT = register(Command("plants.update", "/plants/{id}/update", ADMIN, _update_plant))
UPDATE_SETTINGS = register(
    Command("tenant_settings.update", "/tenant/settings/update", ADMIN, _update_settings)
)
