"""Auth jobs (queue `notifications`): the password-reset email. Runs in the worker, inside `tenant_tx` (ADR-006)."""

from uuid import UUID

import structlog
from sqlalchemy import select

from app.core.auth import otp
from app.core.auth.job_refs import SEND_PASSWORD_RESET
from app.core.db import current_session
from app.core.jobs import job
from app.core.mail import send_email
from app.core.models import User

log = structlog.get_logger("auth.jobs")


@job(SEND_PASSWORD_RESET)
def send_password_reset(tenant_id: str, user_id: str, request_nonce: str) -> None:
    """Email a reset code to an active user. Unknown or inactive users get nothing (the API never says which)."""
    session = current_session()
    uid = UUID(user_id)
    user = session.execute(
        select(User.email, User.active).where(User.tenant_id == UUID(tenant_id), User.id == uid)
    ).first()
    if user is None or not user.active:
        log.info("password_reset_skipped", user_id=user_id)
        return
    code = otp.code_for_request(request_nonce, uid)
    otp.store(uid, code)
    send_email(
        to=user.email,
        subject="Reset your QualLoop password",
        body=(
            f"Your QualLoop password reset code is {code}.\n\n"
            f"It works for {otp.TTL_SECONDS // 60} minutes and only once. "
            "If you did not ask for this, ignore this email; your password has not changed.\n"
        ),
        idempotency_key=f"{request_nonce}:password_reset:{user_id}",
    )
