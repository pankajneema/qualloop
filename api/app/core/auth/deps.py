"""Request authentication, CSRF and permission dependencies (ADR-008).

Order for every protected route: session (401) -> CSRF on unsafe methods (403) -> permission (403) -> body validation.
FastAPI solves dependencies before it validates the body, so a caller who may not use an endpoint learns nothing about
its input rules or about which objects exist.
"""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select

from app.core.auth import sessions
from app.core.config import get_settings
from app.core.db import read_tx
from app.core.errors import Forbidden, Unauthenticated
from app.core.logging import bind_actor_context
from app.core.models import User
from app.core.permissions import ACTOR_USER, Actor, Permission, check_permission
from app.core.redis_client import get_redis

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
_UNAUTHENTICATED = "Sign in to continue."


def client_ip(request: Request) -> str | None:
    """The socket peer. Behind the load balancer the platform sets the peer; X-Forwarded-For is not trusted here."""
    return request.client.host if request.client else None


def _authenticate(request: Request) -> Actor:
    redis = get_redis()
    token = request.cookies.get(sessions.SESSION_COOKIE)
    session = sessions.load_session(redis, token)
    if session is None:
        raise Unauthenticated(_UNAUTHENTICATED)
    with read_tx(session.tenant_id, ACTOR_USER, session.user_id) as db:
        row = db.execute(
            select(User.role, User.can_approve, User.plant_ids, User.active).where(
                User.tenant_id == session.tenant_id, User.id == session.user_id
            )
        ).first()
    if row is None or not row.active:
        # A deactivated user's sessions are also deleted at deactivation; this is the defence in depth.
        sessions.delete_session(redis, token, session.user_id)
        raise Unauthenticated(_UNAUTHENTICATED)
    return Actor(
        type=ACTOR_USER,
        user_id=session.user_id,
        tenant_id=session.tenant_id,
        role=row.role,
        can_approve=row.can_approve,
        plant_ids=tuple(row.plant_ids),
        session_id=session.session_id,
        ip=client_ip(request),
    )


async def authenticate(request: Request) -> Actor:
    """The signed-in internal user, loaded fresh (role, can_approve, plants and `active` are never read from the session)."""
    actor = await run_in_threadpool(_authenticate, request)
    request.state.tenant_id = str(actor.tenant_id)
    request.state.actor_type = actor.type
    request.state.user_id = str(actor.user_id)
    bind_actor_context(
        tenant_id=str(actor.tenant_id), actor_type=actor.type, user_id=str(actor.user_id)
    )
    return actor


def verify_csrf(request: Request) -> None:
    """Double-submit token plus Origin check for cookie-authenticated unsafe requests (API.md 1.2)."""
    expected_origin = get_settings().public_base_url.rstrip("/")
    origin = request.headers.get("origin")
    if origin is None or origin.rstrip("/") != expected_origin:
        raise Forbidden("This request came from an unexpected origin.")
    token = request.cookies.get(sessions.SESSION_COOKIE)
    if not token or not sessions.csrf_matches(
        token, request.cookies.get(sessions.CSRF_COOKIE), request.headers.get(sessions.CSRF_HEADER)
    ):
        raise Forbidden("The security token is missing or invalid. Reload the page and try again.")


def require(permission: Permission, *, command: bool = True) -> Callable[..., Awaitable[Actor]]:
    """Dependency factory: authenticate, CSRF on unsafe methods, then `check_permission`."""

    async def dependency(request: Request, actor: Annotated[Actor, Depends(authenticate)]) -> Actor:
        if request.method not in SAFE_METHODS:
            verify_csrf(request)
        check_permission(permission, actor, command=command)
        return actor

    return dependency
