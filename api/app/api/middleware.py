"""Request id + access log. Auth, CSRF and rate limit arrive in P01."""

import re
import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.logging import bind_request_context, clear_request_context

log = structlog.get_logger("access")
_VALID_ID = re.compile(r"^[A-Za-z0-9._-]{8,64}$")
# Magic-link tokens travel in these paths (ADR-009); they must never reach the logs.
_SENSITIVE_PREFIXES = ("/s/", "/supplier-access/", "/api/v1/supplier-access/")


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
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        incoming = request.headers.get("x-request-id", "")
        request_id = incoming if _VALID_ID.match(incoming) else uuid.uuid4().hex
        clear_request_context()
        bind_request_context(request_id)
        start = time.perf_counter()
        status = 500
        try:
            try:
                response = await call_next(request)
            except Exception:
                log.exception("unhandled_error", route=loggable_route(request))
                response = JSONResponse({"detail": "Internal Server Error"}, status_code=500)
            status = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            log.info(
                "request",
                route=loggable_route(request),
                method=request.method,
                status=status,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            clear_request_context()
