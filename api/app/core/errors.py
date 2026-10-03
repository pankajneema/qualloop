"""Application errors and RFC 9457 `application/problem+json` rendering (API.md 1.4, ADR-019).

Every error body carries `type, title, status, code, detail, instance, request_id` (+ `errors[]` for validation).
Nothing internal reaches a client: no stack traces, no exception text of unexpected errors, no SQL, no driver messages.
"""

from collections.abc import Mapping, Sequence
from typing import Any

import psycopg.errors
import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = structlog.get_logger("errors")

PROBLEM_BASE = "https://qualloop.in/problems/"
PROBLEM_MEDIA_TYPE = "application/problem+json"

FieldError = Mapping[str, str]


class AppError(Exception):
    """Base class: subclasses fix the HTTP status, machine code and a safe default title."""

    status: int = 500
    code: str = "internal_error"
    title: str = "Something went wrong"

    def __init__(
        self,
        detail: str | None = None,
        *,
        errors: Sequence[FieldError] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        super().__init__(detail or self.title)
        self.detail = detail
        self.errors = list(errors) if errors else None
        self.headers = dict(headers) if headers else None


class BadRequest(AppError):
    status = 400
    code = "bad_request"
    title = "The request could not be understood"


class Unauthenticated(AppError):
    status = 401
    code = "unauthenticated"
    title = "You need to sign in"


class Forbidden(AppError):
    status = 403
    code = "forbidden"
    title = "You do not have permission to do this"


class NotFound(AppError):
    status = 404
    code = "not_found"
    title = "We could not find that"


class InvalidTransition(AppError):
    status = 409
    code = "invalid_transition"
    title = "This cannot be done in its current state"


class Conflict(AppError):
    status = 409
    code = "conflict"
    title = "This conflicts with another change"


class PayloadTooLarge(AppError):
    status = 413
    code = "payload_too_large"
    title = "That is too large"


class UnsupportedMediaType(AppError):
    status = 415
    code = "unsupported_media_type"
    title = "That file type is not supported"


class ValidationFailed(AppError):
    status = 422
    code = "validation_error"
    title = "Some details need fixing"


class InvariantViolation(AppError):
    status = 422
    code = "invariant_violation"
    title = "This change breaks a data rule"


class IdempotencyMismatch(AppError):
    status = 422
    code = "idempotency_mismatch"
    title = "That Idempotency-Key was already used for a different request"


class RateLimited(AppError):
    status = 429
    code = "rate_limited"
    title = "Too many attempts"

    def __init__(self, retry_after: int, detail: str | None = None) -> None:
        self.retry_after = max(1, int(retry_after))
        super().__init__(detail, headers={"Retry-After": str(self.retry_after)})


def field_error(field: str, code: str, message: str) -> dict[str, str]:
    return {"field": field, "code": code, "message": message}


class ProblemField(BaseModel):
    field: str
    code: str
    message: str


class Problem(BaseModel):
    """RFC 9457 error body (OpenAPI schema of every non-2xx response)."""

    type: str
    title: str
    status: int
    code: str
    detail: str
    instance: str
    request_id: str
    errors: list[ProblemField] | None = None


PROBLEM_RESPONSES: dict[int | str, dict[str, Any]] = {
    status: {"model": Problem, "description": description, "content": {PROBLEM_MEDIA_TYPE: {}}}
    for status, description in (
        (400, "Malformed JSON or cursor (bad_request)"),
        (401, "No or expired session (unauthenticated)"),
        (403, "Role, can_approve or CSRF check failed (forbidden)"),
        (404, "Absent, other tenant or outside scope (not_found)"),
        (409, "invalid_transition or conflict"),
        (413, "payload_too_large"),
        (415, "unsupported_media_type"),
        (422, "validation_error, invariant_violation or idempotency_mismatch"),
        (429, "rate_limited (Retry-After header)"),
    )
}


# ----------------------------------------------------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------------------------------------------------
def request_id_of(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    return str(value) if value else ""


def problem_response(
    request: Request,
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    errors: Sequence[FieldError] | None = None,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    body: dict[str, Any] = {
        "type": PROBLEM_BASE + code.replace("_", "-"),
        "title": title,
        "status": status,
        "code": code,
        "detail": detail or title,
        "instance": request.url.path,
        "request_id": request_id_of(request),
    }
    if errors:
        body["errors"] = [dict(e) for e in errors]
    response = JSONResponse(body, status_code=status, media_type=PROBLEM_MEDIA_TYPE)
    for name, value in (headers or {}).items():
        response.headers[name] = value
    return response


def internal_error_response(request: Request) -> JSONResponse:
    return problem_response(
        request,
        status=500,
        code="internal_error",
        title="Something went wrong on our side",
        detail="We could not complete this. Nothing was changed. Try again, and quote the request id if it persists.",
    )


async def _app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return problem_response(
        request,
        status=exc.status,
        code=exc.code,
        title=exc.title,
        detail=exc.detail,
        errors=exc.errors,
        headers=exc.headers,
    )


def _field_name(loc: Sequence[Any]) -> str:
    parts = [str(p) for p in loc if p not in ("body", "query", "path", "header", "cookie")]
    return ".".join(parts)


async def _validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    raw = exc.errors()
    if any(e.get("type") == "json_invalid" for e in raw):
        return problem_response(
            request,
            status=400,
            code="bad_request",
            title=BadRequest.title,
            detail="The request body is not valid JSON.",
        )
    errors = [
        field_error(
            _field_name(e.get("loc", ())),
            str(e.get("type", "invalid")),
            str(e.get("msg", "Invalid value.")),
        )
        for e in raw
    ]
    return problem_response(
        request,
        status=422,
        code="validation_error",
        title=ValidationFailed.title,
        detail="Check the highlighted details and try again.",
        errors=errors,
    )


_HTTP_CODES: dict[int, tuple[str, str]] = {
    400: ("bad_request", BadRequest.title),
    401: ("unauthenticated", Unauthenticated.title),
    403: ("forbidden", Forbidden.title),
    404: ("not_found", NotFound.title),
    405: ("method_not_allowed", "That method is not allowed here"),
    413: ("payload_too_large", PayloadTooLarge.title),
    415: ("unsupported_media_type", UnsupportedMediaType.title),
}


async def _http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code, title = _HTTP_CODES.get(exc.status_code, ("http_error", "The request failed"))
    return problem_response(
        request,
        status=exc.status_code,
        code=code,
        title=title,
        headers=exc.headers,
    )


def map_db_error(exc: DBAPIError) -> AppError | None:
    """Translate a database error into an application error, or None when it is not a client-visible condition."""
    orig = exc.orig
    if isinstance(orig, psycopg.errors.InsufficientPrivilege):
        # Row-level security rejects a write to a row of another tenant: indistinguishable from "not found".
        if "row-level security" in str(orig):
            return NotFound()
        return None
    if isinstance(orig, psycopg.errors.UniqueViolation):
        return Conflict("This already exists.")
    if isinstance(
        orig,
        psycopg.errors.CheckViolation
        | psycopg.errors.RaiseException
        | psycopg.errors.IntegrityConstraintViolation,
    ):
        return InvariantViolation("The change breaks a data rule and was not saved.")
    if isinstance(
        orig,
        psycopg.errors.DeadlockDetected
        | psycopg.errors.SerializationFailure
        | psycopg.errors.LockNotAvailable,
    ):
        return Conflict("Another change was happening at the same time. Reload and try again.")
    return None


async def _db_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DBAPIError)
    mapped = map_db_error(exc)
    diag = getattr(exc.orig, "diag", None)
    # Operators see which rule fired (constraint / trigger name); the client never does.
    log.warning(
        "database_error" if mapped is None else "database_rule_violation",
        error_type=type(exc.orig).__name__,
        sqlstate=getattr(exc.orig, "sqlstate", None),
        constraint=getattr(diag, "constraint_name", None),
        table=getattr(diag, "table_name", None),
        mapped_status=mapped.status if mapped else 500,
    )
    if mapped is None:
        return internal_error_response(request)
    return await _app_error_handler(request, mapped)


def register_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_exception_handler)
    app.add_exception_handler(DBAPIError, _db_error_handler)
