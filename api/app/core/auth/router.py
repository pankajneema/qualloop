"""Auth endpoints (API.md 3.1, ADR-008): login, logout, password reset by emailed code.

None of these is a registered `Command`: login/logout/reset act on the caller's own credentials, not on domain objects.
Login and reset still write to `activity_log` (and reset to the outbox) in the same transaction as their change.
"""

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import structlog
from fastapi import Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from app.core import ratelimit
from app.core.audit.writer import record_activity
from app.core.auth import otp, sessions
from app.core.auth.deps import client_ip, require
from app.core.auth.job_refs import SEND_PASSWORD_RESET
from app.core.auth.passwords import hash_password, verify_password
from app.core.auth.schemas import (
    Accepted,
    LoginRequest,
    LoginResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
)
from app.core.config import get_settings
from app.core.db import get_engine, tenant_tx
from app.core.errors import Forbidden, RateLimited, Unauthenticated, ValidationFailed, field_error
from app.core.ids import new_id
from app.core.jobs import enqueue
from app.core.models import User
from app.core.outbox.writer import emit_event
from app.core.permissions import ACTOR_USER, ANY_USER, Actor
from app.core.redis_client import get_redis
from app.core.routing import api_router

log = structlog.get_logger("auth")

router = api_router("/auth", tags=["auth"])

LOGIN_FAILURE_LIMIT = 5  # per email and per IP (API.md section 6)
LOGIN_WINDOW_SECONDS = 15 * 60
RESET_REQUEST_LIMIT = 3  # per email
RESET_WINDOW_SECONDS = 3600

_BAD_CREDENTIALS = "The email or password is not correct."
_BAD_CODE = "That code is not valid or has expired. Ask for a new one."


def _normalise(email: str) -> str:
    return email.strip().lower()


def _check_origin(request: Request) -> None:
    """Public POSTs have no session to bind a token to; a browser still sends Origin, and a foreign one is refused."""
    origin = request.headers.get("origin")
    if origin is not None and origin.rstrip("/") != get_settings().public_base_url.rstrip("/"):
        raise Forbidden("This request came from an unexpected origin.")


@dataclass(frozen=True)
class _Resolved:
    tenant_id: UUID
    user_id: UUID


def _resolve(email: str) -> _Resolved | None:
    """Email -> (tenant, user) through the definer function: login happens before any tenant context exists."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text("SELECT tenant_id, user_id FROM app_resolve_login(:email)"), {"email": email}
        ).first()
    return _Resolved(row.tenant_id, row.user_id) if row else None


def _set_session_cookies(response: Response, token: str) -> None:
    max_age = sessions.ABSOLUTE_SECONDS
    response.set_cookie(
        sessions.SESSION_COOKIE,
        token,
        max_age=max_age,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )
    # Readable by the page's JavaScript: the double-submit token is echoed in the X-CSRF-Token header.
    response.set_cookie(
        sessions.CSRF_COOKIE,
        sessions.csrf_token_for(token),
        max_age=max_age,
        secure=True,
        httponly=False,
        samesite="lax",
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(
        sessions.SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax"
    )
    response.delete_cookie(
        sessions.CSRF_COOKIE, path="/", secure=True, httponly=False, samesite="lax"
    )


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request) -> JSONResponse:
    _check_origin(request)
    email = _normalise(body.email)
    ip = client_ip(request) or "unknown"
    counters = [f"rl:login:email:{ratelimit.key_part(email)}", f"rl:login:ip:{ip}"]
    wait = ratelimit.blocked_for(counters, limit=LOGIN_FAILURE_LIMIT)
    if wait:
        raise RateLimited(wait, "Too many sign-in attempts. Try again later.")

    resolved = _resolve(email)
    session_token: str | None = None
    try:
        if resolved is None:
            verify_password(None, body.password)  # same cost as a real check
        else:
            with tenant_tx(resolved.tenant_id, ACTOR_USER, resolved.user_id) as db:
                user = db.execute(
                    select(
                        User.email,
                        User.name,
                        User.role,
                        User.can_approve,
                        User.active,
                        User.password_hash,
                    ).where(User.tenant_id == resolved.tenant_id, User.id == resolved.user_id)
                ).first()
                verified = verify_password(user.password_hash if user else None, body.password)
                if user is not None and user.active and verified:
                    session_token, data = sessions.create_session(
                        get_redis(),
                        user_id=resolved.user_id,
                        tenant_id=resolved.tenant_id,
                        ip=client_ip(request),
                        user_agent=request.headers.get("user-agent"),
                    )
                    record_activity(
                        db,
                        actor=Actor(
                            type=ACTOR_USER,
                            user_id=resolved.user_id,
                            tenant_id=resolved.tenant_id,
                            role=user.role,
                            can_approve=user.can_approve,
                            plant_ids=(),
                            session_id=data.session_id,
                            ip=client_ip(request),
                        ),
                        object_type="user",
                        object_id=resolved.user_id,
                        action="auth.login",
                    )
                    result = LoginResponse(
                        email=user.email,
                        name=user.name,
                        role=user.role,
                        can_approve=user.can_approve,
                    )
    except BaseException:
        if session_token is not None:  # the session must not outlive a login that did not commit
            sessions.delete_session(get_redis(), session_token)
        raise

    if session_token is None:
        # One generic answer for unknown email, wrong password, inactive user and no password set.
        ratelimit.record(counters, window_seconds=LOGIN_WINDOW_SECONDS)
        raise Unauthenticated(_BAD_CREDENTIALS)

    response = JSONResponse(result.model_dump())
    _set_session_cookies(response, session_token)
    return response


@router.post("/logout", status_code=204, response_class=Response)
def logout(
    request: Request, actor: Annotated[Actor, Depends(require(ANY_USER, command=False))]
) -> Response:
    sessions.delete_session(
        get_redis(), request.cookies.get(sessions.SESSION_COOKIE), actor.user_id
    )
    response = Response(status_code=204)
    _clear_session_cookies(response)
    return response


@router.post("/password-reset/request", response_model=Accepted, status_code=202)
def request_password_reset(body: PasswordResetRequest, request: Request) -> Accepted:
    """Always answers 202, whatever the email is. The worker emails a code only to an active user."""
    _check_origin(request)
    email = _normalise(body.email)
    ratelimit.hit(
        f"rl:pwreset:{ratelimit.key_part(email)}",
        limit=RESET_REQUEST_LIMIT,
        window_seconds=RESET_WINDOW_SECONDS,
    )
    resolved = _resolve(email)
    if resolved is not None:
        # The message carries ids and a nonce, never the address or the code (it sits in Redis until a worker takes it).
        enqueue(
            SEND_PASSWORD_RESET,
            tenant_id=str(resolved.tenant_id),
            user_id=str(resolved.user_id),
            request_nonce=str(new_id()),
        )
    return Accepted()


@router.post("/password-reset/confirm", response_model=Accepted, status_code=202)
def confirm_password_reset(body: PasswordResetConfirm, request: Request) -> Accepted:
    _check_origin(request)
    invalid = ValidationFailed(_BAD_CODE, errors=[field_error("otp", "invalid", _BAD_CODE)])
    resolved = _resolve(_normalise(body.email))
    if resolved is None:
        raise invalid
    with tenant_tx(resolved.tenant_id, ACTOR_USER, resolved.user_id) as db:
        user = db.execute(
            select(User)
            .where(User.tenant_id == resolved.tenant_id, User.id == resolved.user_id)
            .with_for_update()
        ).scalar_one_or_none()
        if user is None or not user.active:
            raise invalid
        if not otp.consume(resolved.user_id, body.otp):
            raise invalid
        user.password_hash = hash_password(body.new_password)
        user.updated_by = user.id
        db.flush()
        actor = Actor(
            type=ACTOR_USER,
            user_id=user.id,
            tenant_id=user.tenant_id,
            role=user.role,
            can_approve=user.can_approve,
            plant_ids=(),
            ip=client_ip(request),
        )
        record_activity(
            db,
            actor=actor,
            object_type="user",
            object_id=user.id,
            action="user.password_reset",
            after={"password_changed": True},
            reason="Password reset with an emailed code.",
        )
        emit_event(
            db,
            actor=actor,
            aggregate_type="user",
            aggregate_id=user.id,
            event_type="USER_PASSWORD_RESET",
            payload={"user_id": str(user.id)},
        )
    try:  # after commit: every existing session of this user ends (the password changed)
        sessions.delete_user_sessions(get_redis(), resolved.user_id)
    except Exception:
        log.error(
            "password_reset_session_cleanup_failed", user_id=str(resolved.user_id), exc_info=True
        )
    return Accepted()
