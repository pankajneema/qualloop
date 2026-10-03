"""Outgoing channels for contact verification codes (A-110). Only workers call this module (INV-PLT-11).

Email goes through the real SMTP path (`app.core.mail`). Mobile delivery (WhatsApp/SMS) arrives in P05; until then the
dev fake channel records the message in `FAKE_SENT`, and only in `QL_ENV` local and ci. In staging and production a
mobile code cannot be sent, so `verify/start` refuses the mobile channel there (`mobile_channel_available`).
"""

import structlog

from app.core.config import get_settings
from app.core.mail import send_email

log = structlog.get_logger("masters.channels")

# SPEC-GAP: A-110 - mobile OTP delivery before WhatsApp/SMS exist: the dev fake channel below.
FAKE_SENT: list[dict[str, str]] = []

_FAKE_ENVS = ("local", "ci")


class ChannelUnavailable(RuntimeError):
    """The channel cannot deliver in this environment."""


def mobile_channel_available() -> bool:
    return get_settings().env in _FAKE_ENVS


def send_mobile(*, to: str, body: str, idempotency_key: str) -> None:
    """Record one message on the fake mobile channel; a repeated idempotency key sends nothing."""
    if not mobile_channel_available():
        raise ChannelUnavailable("mobile delivery is not available before P05")
    if any(m["idempotency_key"] == idempotency_key for m in FAKE_SENT):
        return
    FAKE_SENT.append(
        {"channel": "mobile", "to": to, "body": body, "idempotency_key": idempotency_key}
    )
    log.info("fake_mobile_sent")


def send_code(*, channel: str, to: str, code: str, ttl_minutes: int, idempotency_key: str) -> None:
    """Deliver a verification code on `channel` ("mobile" or "email")."""
    body = (
        f"Your QualLoop verification code is {code}. "
        f"It works for {ttl_minutes} minutes. If you did not expect this, ignore this message."
    )
    if channel == "email":
        send_email(
            to=to,
            subject="Your QualLoop verification code",
            body=body + "\n",
            idempotency_key=idempotency_key,
        )
    else:
        send_mobile(to=to, body=body, idempotency_key=idempotency_key)
