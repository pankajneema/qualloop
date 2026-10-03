"""Request id, access log, JSON body size limit and baseline response headers (ADR-015, ADR-019).

Authentication, CSRF and rate limiting are request dependencies (`app.core.auth`), not middleware: they need the route's
permission, and dependencies run before the request body is validated.
"""

import re
import time
import uuid
from collections.abc import MutableMapping
from typing import Any

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.errors import PayloadTooLarge, internal_error_response, problem_response
from app.core.logging import bind_request_context, clear_request_context

log = structlog.get_logger("access")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Magic-link tokens travel in these paths (ADR-009); they must never reach the logs.
_SENSITIVE_PREFIXES = ("/s/", "/supplier-access/", "/api/v1/supplier-access/")

MAX_JSON_BODY_BYTES = 1024 * 1024  # ADR-019: size limits on JSON bodies (1 MB)


def loggable_route(request: Request) -> str:
    """Route template (e.g. /s/{token}) or '<unmatched>'; never the raw path."""
    route = request.scope.get("route")
    template = getattr(route, "path", None)
    if not template:
        return "<unmatched>"
    if template.startswith(_SENSITIVE_PREFIXES) and "{" not in template:
        return "<redacted>"
    return str(template)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Outermost: request id in/out, access log line, last-resort 500 problem, baseline security headers.

    Who made the request (tenant, actor, user) is recorded by the authentication dependency on `request.state`, which
    is shared with this middleware through the ASGI scope, and added to the access log line here."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        request.state.request_id = request_id
        clear_request_context()
        bind_request_context(request_id)
        start = time.perf_counter()
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                log.exception("unhandled_error", route=loggable_route(request))
                response = internal_error_response(request)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            if request.url.path.startswith("/api/"):
                response.headers.setdefault("Cache-Control", "no-store")
            return response
        finally:
            state = request.state
            fields: dict[str, Any] = {}
            for name in ("tenant_id", "actor_type", "user_id"):
                value = getattr(state, name, None)
                if value:
                    fields[name] = value
            log.info(
                "request",
                route=loggable_route(request),
                method=request.method,
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
                **fields,
            )
            clear_request_context()


class BodySizeLimitMiddleware:
    """Reject request bodies over `MAX_JSON_BODY_BYTES` with 413 problem+json (declared or streamed size)."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_JSON_BODY_BYTES) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = _declared_length(scope)
        if declared is not None and declared > self.max_bytes:
            request = Request(scope)
            response = problem_response(
                request,
                status=413,
                code="payload_too_large",
                title=PayloadTooLarge.title,
                detail="The request body is too large.",
            )
            await response(scope, receive, send)
            return
        received = 0
        limit = self.max_bytes

        async def limited_receive() -> MutableMapping[str, Any]:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise PayloadTooLarge("The request body is too large.")
            return message

        await self.app(scope, limited_receive, send)


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
