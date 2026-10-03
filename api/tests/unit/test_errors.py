"""API.md 1.4: RFC 9457 problem+json for every error, request_id, DB error mapping, no stack traces (ADR-019)."""

from collections.abc import Callable, Iterator
from typing import Any

import psycopg.errors
import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel
from sqlalchemy.exc import DBAPIError

from app.main import create_app
from tests.factories.contract import load

SECRET_TEXT = "boom-secret-internal-detail"
SQL_TEXT = "SELECT secret_column FROM hidden_table"


class Body(BaseModel):
    n: int


def _client(**routes: Callable[[], Any]) -> Iterator[TestClient]:
    app: FastAPI = create_app()
    router = APIRouter()
    for name, fn in routes.items():
        router.add_api_route(f"/zz/{name}", fn, methods=["GET"])

    def post_body(body: Body) -> dict[str, int]:
        return {"n": body.n}

    router.add_api_route("/zz/post-body", post_body, methods=["POST"])
    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def _raiser(exc: Exception) -> Callable[[], Any]:
    def route() -> None:
        raise exc

    return route


def _db_error(orig: Exception) -> DBAPIError:
    return DBAPIError(SQL_TEXT, {"p": 1}, orig)


def _assert_problem(resp: Any, status: int, code: str) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    assert resp.headers["content-type"].startswith("application/problem+json")
    body = resp.json()
    assert body["status"] == status
    assert body["code"] == code
    assert body["type"] == f"https://qualloop.in/problems/{code.replace('_', '-')}"
    assert body["title"]
    assert body["instance"] == resp.request.url.path
    assert body["request_id"] == resp.headers["x-request-id"]
    assert SECRET_TEXT not in resp.text
    assert SQL_TEXT not in resp.text
    assert "Traceback" not in resp.text
    return body  # type: ignore[no-any-return]


APP_ERRORS = [
    ("Unauthenticated", 401, "unauthenticated"),
    ("Forbidden", 403, "forbidden"),
    ("NotFound", 404, "not_found"),
    ("InvalidTransition", 409, "invalid_transition"),
    ("Conflict", 409, "conflict"),
    ("PayloadTooLarge", 413, "payload_too_large"),
    ("UnsupportedMediaType", 415, "unsupported_media_type"),
    ("InvariantViolation", 422, "invariant_violation"),
    ("IdempotencyMismatch", 422, "idempotency_mismatch"),
]


@pytest.mark.parametrize(("name", "status", "code"), APP_ERRORS)
def test_app_errors_render_problem_json_with_status_code_type_and_request_id(
    name: str, status: int, code: str
) -> None:
    exc = load("app.core.errors", name)(f"safe detail for {name}")
    for client in _client(raise_it=_raiser(exc)):
        resp = client.get("/zz/raise_it", headers={"X-Request-ID": "req-errors-0001"})
        body = _assert_problem(resp, status, code)
        assert body["detail"] == f"safe detail for {name}"
        assert resp.headers["x-request-id"] == "req-errors-0001"


def test_rate_limited_is_429_with_retry_after_header() -> None:
    exc = load("app.core.errors", "RateLimited")(retry_after=120)
    for client in _client(limited=_raiser(exc)):
        resp = client.get("/zz/limited")
        _assert_problem(resp, 429, "rate_limited")
        assert resp.headers["retry-after"] == "120"


def test_validation_error_is_422_with_field_code_message_entries() -> None:
    for client in _client():
        resp = client.post("/zz/post-body", json={"n": "not-a-number"})
        body = _assert_problem(resp, 422, "validation_error")
        entry = body["errors"][0]
        assert entry["field"] == "n"
        assert entry["code"]
        assert entry["message"]


def test_malformed_json_is_400_bad_request() -> None:
    for client in _client():
        resp = client.post(
            "/zz/post-body", content=b'{"n": ', headers={"Content-Type": "application/json"}
        )
        _assert_problem(resp, 400, "bad_request")


def test_unknown_route_is_404_problem_json_not_the_framework_default() -> None:
    for client in _client():
        _assert_problem(client.get("/api/v1/definitely-not-a-route"), 404, "not_found")


def test_unhandled_exception_is_500_internal_error_without_stack_trace_or_message() -> None:
    for client in _client(crash=_raiser(RuntimeError(SECRET_TEXT))):
        resp = client.get("/zz/crash", headers={"X-Request-ID": "req-crash-000001"})
        _assert_problem(resp, 500, "internal_error")
        assert "RuntimeError" not in resp.text
        assert 'File "' not in resp.text


@pytest.mark.parametrize(
    ("orig", "status", "code"),
    [
        (psycopg.errors.CheckViolation(SECRET_TEXT), 422, "invariant_violation"),
        (psycopg.errors.RaiseException(SECRET_TEXT), 422, "invariant_violation"),
        (psycopg.errors.IntegrityConstraintViolation(SECRET_TEXT), 422, "invariant_violation"),
        (psycopg.errors.DeadlockDetected(SECRET_TEXT), 409, "conflict"),
        (psycopg.errors.SerializationFailure(SECRET_TEXT), 409, "conflict"),
    ],
    ids=["check", "trigger-raise", "trigger-integrity", "deadlock", "serialization"],
)
def test_database_errors_map_to_documented_statuses_without_leaking_sql(
    orig: Exception, status: int, code: str
) -> None:
    for client in _client(db=_raiser(_db_error(orig))):
        _assert_problem(client.get("/zz/db"), status, code)


def test_row_level_security_violation_maps_to_404_never_revealing_existence() -> None:
    orig = psycopg.errors.InsufficientPrivilege(
        'new row violates row-level security policy for table "plants"'
    )
    for client in _client(rls=_raiser(_db_error(orig))):
        _assert_problem(client.get("/zz/rls"), 404, "not_found")


def test_unique_violation_maps_to_a_client_error_not_500() -> None:
    orig = psycopg.errors.UniqueViolation(SECRET_TEXT)
    for client in _client(dup=_raiser(_db_error(orig))):
        resp = client.get("/zz/dup")
        assert resp.status_code in (409, 422), resp.text
        assert resp.headers["content-type"].startswith("application/problem+json")
        assert SECRET_TEXT not in resp.text
        assert SQL_TEXT not in resp.text


def test_hostile_request_id_is_replaced_and_error_body_carries_the_replacement() -> None:
    exc = load("app.core.errors", "Forbidden")("no")
    for client in _client(raise_it=_raiser(exc)):
        resp = client.get("/zz/raise_it", headers={"X-Request-ID": "x injected\nlog line"})
        body = resp.json()
        assert body["request_id"] == resp.headers["x-request-id"]
        assert "injected" not in body["request_id"]
