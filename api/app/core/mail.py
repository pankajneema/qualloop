"""Outgoing email (SMTP; Mailpit locally). Only workers call this: the HTTP layer enqueues jobs (INV-PLT-11).

`send_email` needs an `idempotency_key`, stamps it on the message as `X-Idempotency-Key`, and a second call with the same
key delivers nothing, so a redelivered job never sends twice (blueprint 22.2). The key is claimed in Redis (`idem:mail:*`)
before sending and released if sending fails, so a retry can still send.
"""

import hashlib
import smtplib
from email import policy
from email.message import EmailMessage

import structlog

from app.core.config import get_settings
from app.core.redis_client import get_redis

log = structlog.get_logger("mail")

_PENDING_SECONDS = 300
_SENT_SECONDS = 7 * 24 * 3600
SMTP_TIMEOUT_SECONDS = 15
# Keep `X-Idempotency-Key` readable: with the default 78-column limit a long key is RFC 2047-encoded.
_POLICY = policy.SMTP.clone(max_line_length=998)


class SendInFlight(RuntimeError):
    """Another worker holds this idempotency key and has not finished: retry later."""


def _key(idempotency_key: str) -> str:
    return "idem:mail:" + hashlib.sha256(idempotency_key.encode()).hexdigest()


def send_email(*, to: str, subject: str, body: str, idempotency_key: str) -> None:
    """Send one plain-text email exactly once per `idempotency_key` (at-most-once per key within 7 days)."""
    if not idempotency_key:
        raise ValueError("idempotency_key is required")
    redis = get_redis()
    key = _key(idempotency_key)
    if not redis.set(key, "pending", nx=True, ex=_PENDING_SECONDS):
        if redis.get(key) == "sent":
            log.info("email_skipped_duplicate")
            return
        raise SendInFlight("a send with this idempotency key is already in progress")
    settings = get_settings()
    message = EmailMessage(policy=_POLICY)
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message["X-Idempotency-Key"] = idempotency_key
    message.set_content(body)
    try:
        with smtplib.SMTP(
            settings.smtp_host, settings.smtp_port, timeout=SMTP_TIMEOUT_SECONDS
        ) as smtp:
            smtp.send_message(message)
    except Exception:
        redis.delete(key)  # nothing was sent: let the retry send
        raise
    redis.set(key, "sent", ex=_SENT_SECONDS)
    log.info("email_sent")
