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
            await self._too_large(scope, receive, send)
            return
        # No Content-Length (chunked) or a declared length that is within the limit: read the body here, counting, so
        # that THIS middleware answers 413 the moment the limit is crossed. (Raising inside `receive` would surface as a
        # 400/500 from whatever parses the body.) A body is at most `max_bytes`, so buffering it is cheap.
        buffered: list[MutableMapping[str, Any]] = []
        received = 0
        while True:
            message = await receive()
            buffered.append(message)
            if message["type"] != "http.request":  # client went away
                break
            received += len(message.get("body", b""))
            if received > self.max_bytes:
                await self._too_large(scope, receive, send)
                return
            if not message.get("more_body", False):
                break

        async def replay() -> MutableMapping[str, Any]:
            if buffered:
                return buffered.pop(0)
            return await receive()

        await self.app(scope, replay, send)

    @staticmethod
    async def _too_large(scope: Scope, receive: Receive, send: Send) -> None:
        response = problem_response(
            Request(scope),
            status=413,
            code="payload_too_large",
            title=PayloadTooLarge.title,
            detail="The request body is too large.",
        )
        await response(scope, receive, send)


def _declared_length(scope: Scope) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            try:
                return int(value)
            except ValueError:
                return None
    return None
