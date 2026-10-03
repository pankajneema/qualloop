"""Authorisation rules (API.md 1.3, ADR-008): role sets, +CA, A-or-CA, plant scope, actor types.

Rules:
  * Admin holds every Quality permission (A-70); Quality also holds Viewer (read) permissions.
  * Viewer is read-only: never allowed on a command, whatever the permission lists.
  * `requires_can_approve` (+CA) needs the flag on top of the role; Admin does NOT bypass it.
  * `admin_or_can_approve` (A or CA) accepts Admin or a user with the flag.
  * `ai` and `supplier_session` actors never pass an internal permission (INV-AI-02, ADR-009).
  * Plant scope (A-04): Admin sees all plants; Quality/Viewer only `plant_ids` (empty list = none).
"""

from dataclasses import dataclass
from uuid import UUID

from app.core.errors import Forbidden

ROLE_ADMIN = "admin"
ROLE_QUALITY = "quality"
ROLE_VIEWER = "viewer"
ROLES = (ROLE_ADMIN, ROLE_QUALITY, ROLE_VIEWER)

ACTOR_USER = "user"
ACTOR_SUPPLIER = "supplier_session"
ACTOR_SYSTEM = "system"
ACTOR_AI = "ai"
ACTOR_TYPES = (ACTOR_USER, ACTOR_SUPPLIER, ACTOR_SYSTEM, ACTOR_AI)


@dataclass(frozen=True)
class Actor:
    """Who is acting. `user_id` is the users.id (internal) or contact id (supplier); NULL for system / ai."""

    type: str
    user_id: UUID | None
    tenant_id: UUID
    role: str
    can_approve: bool
    plant_ids: tuple[UUID, ...]
    session_id: UUID | None = None
    ip: str | None = None


@dataclass(frozen=True)
class Permission:
    roles: frozenset[str]
    requires_can_approve: bool = False
    admin_or_can_approve: bool = False


ADMIN = Permission(frozenset({ROLE_ADMIN}))
QUALITY = Permission(frozenset({ROLE_ADMIN, ROLE_QUALITY}))
ANY_USER = Permission(frozenset(ROLES))

_DENIED = "You do not have permission to do this."


def _role_allows(permission: Permission, role: str) -> bool:
    roles = permission.roles
    if role == ROLE_ADMIN:
        return bool(roles)
    if role == ROLE_QUALITY:
        return ROLE_QUALITY in roles or ROLE_VIEWER in roles
    if role == ROLE_VIEWER:
        return ROLE_VIEWER in roles
    return False


def check_permission(permission: Permission, actor: Actor, *, command: bool) -> None:
    """Raise `Forbidden` unless `actor` may exercise `permission`. `command=True` for state-changing endpoints."""
    if actor.type != ACTOR_USER:
        raise Forbidden(_DENIED)
    if actor.role == ROLE_VIEWER and command:
        raise Forbidden(_DENIED)
    if not _role_allows(permission, actor.role):
        raise Forbidden(_DENIED)
    if permission.requires_can_approve and not actor.can_approve:
        raise Forbidden(_DENIED)
    if permission.admin_or_can_approve and not (actor.role == ROLE_ADMIN or actor.can_approve):
        raise Forbidden(_DENIED)


def plant_in_scope(actor: Actor, plant_id: UUID) -> bool:
    if actor.role == ROLE_ADMIN:
        return True
    return plant_id in actor.plant_ids
