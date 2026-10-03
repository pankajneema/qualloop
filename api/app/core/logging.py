"""structlog JSON logging. request_id / tenant_id live in contextvars (ADR-015).

PII rules (ADR-015 / ADR-019): mobile numbers and email addresses are masked wherever they appear in a log value;
fields that carry secrets (tokens, OTPs, passwords, cookies, authorization) are redacted by name. Request bodies
are never logged.
"""

import logging
import re
import sys
from collections.abc import Mapping
from typing import Any

import structlog

REDACTED = "[redacted]"
_SECRET_FIELDS = frozenset(
    {"token", "otp", "password", "password_hash", "authorization", "cookie", "set-cookie", "secret"}
)
_SECRET_SUFFIXES = ("_token", "_otp", "_password", "_secret", "_hash")

_MOBILE = re.compile(r"\+[1-9][0-9]{7,14}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def mask_mobile(value: str) -> str:
    """`+919876543210` -> `+91******3210` (country code and last four digits kept)."""
    if len(value) <= 7:
        return value[:1] + "*" * max(len(value) - 1, 0)
    return value[:3] + "*" * (len(value) - 7) + value[-4:]


def mask_email(value: str) -> str:
    """`rahul.sharma@example.com` -> `r***@example.com`."""
    local, _, domain = value.partition("@")
    if not domain:
        return "***"
    return f"{local[:1]}***@{domain}"


def mask_text(value: str) -> str:
    value = _EMAIL.sub(lambda m: mask_email(m.group(0)), value)
    return _MOBILE.sub(lambda m: mask_mobile(m.group(0)), value)


def _is_secret_field(name: str) -> bool:
    lowered = name.lower()
    return lowered in _SECRET_FIELDS or lowered.endswith(_SECRET_SUFFIXES)


def _scrub(value: Any, depth: int = 0) -> Any:
    if isinstance(value, str):
        return mask_text(value)
    if depth > 6:
        return value
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if isinstance(k, str) and _is_secret_field(k) else _scrub(v, depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, list | tuple):
        return [_scrub(v, depth + 1) for v in value]
    return value


def pii_processor(
    _logger: Any, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    """structlog processor: redact secret-named fields and mask mobiles/emails in every value."""
    return dict(_scrub(event_dict))


def bind_request_context(request_id: str, tenant_id: str | None = None) -> None:
    structlog.contextvars.bind_contextvars(request_id=request_id, tenant_id=tenant_id)


def bind_actor_context(*, tenant_id: str, actor_type: str, user_id: str | None) -> None:
    structlog.contextvars.bind_contextvars(
        tenant_id=tenant_id, actor_type=actor_type, user_id=user_id
    )


def clear_request_context() -> None:
    structlog.contextvars.clear_contextvars()


def configure_logging(level: str = "INFO", env: str = "local") -> None:
    """JSON to stdout; pretty console renderer only when QL_ENV=local and stdout is a TTY."""
    renderer: structlog.types.Processor
    if env == "local" and sys.stdout.isatty():
        renderer = structlog.dev.ConsoleRenderer()
    else:
        renderer = structlog.processors.JSONRenderer()

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        structlog.processors.format_exc_info,
        pii_processor,
        structlog.processors.EventRenamer("msg"),
    ]
    structlog.configure(
        processors=[*processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=False,
    )
    # Route stdlib logging (uvicorn, sqlalchemy, dramatiq) through the same JSON pipeline.
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
            structlog.processors.format_exc_info,
            pii_processor,
        ],
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log middleware
    # httpx logs full request URLs at INFO; URLs can carry tokens, so keep it quiet.
    logging.getLogger("httpx").setLevel(logging.WARNING)
