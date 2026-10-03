"""ADR-015 / ADR-019: request-scoped structured logs with PII masked, JSON body size limit, strict inputs."""

import json
from contextlib import ExitStack
from typing import Any

import pytest
import redis as redis_lib

from app.core.config import get_settings
from tests.factories.api import ApiFactory, problem
from tests.factories.db import SeededTenant
from tests.integration.commands.test_platform_commands_api import admin_client, new_user_body

pytestmark = pytest.mark.integration


@pytest.fixture
def json_log_api(
    monkeypatch: pytest.MonkeyPatch, engine_env: None, redis_client: redis_lib.Redis
) -> Any:
    """The real app with QL_ENV=ci so logs are JSON lines (local pretty-prints, ADR-015 item 5)."""
    from app.main import create_app

    monkeypatch.setenv("QL_ENV", "ci")
    monkeypatch.setenv("QL_SESSION_SECRET", "s" * 40)
    monkeypatch.setenv("QL_HMAC_SECRET", "h" * 40)
    get_settings.cache_clear()
    with ExitStack() as stack:
        yield ApiFactory(create_app(), stack)
    get_settings.cache_clear()


def log_lines(out: str) -> list[dict[str, Any]]:
    lines = []
    for raw in out.splitlines():
        if raw.startswith("{"):
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
    return lines


def test_access_log_line_carries_request_tenant_actor_route_status_and_duration(
    json_log_api: ApiFactory, seeded: SeededTenant, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seeded.quality
    client = json_log_api.login_as(seeded.quality)
    capsys.readouterr()
    resp = client.get("/me", headers={"X-Request-ID": "req-observ-00001"})
    assert resp.status_code == 200
    mine = [
        r for r in log_lines(capsys.readouterr().out) if r.get("request_id") == "req-observ-00001"
    ]
    assert mine, "no log line carries the request id"
    access = next(r for r in mine if r.get("route"))
    assert access["tenant_id"] == str(seeded.id)
    assert access["actor_type"] == "user" and access["user_id"] == str(seeded.quality.id)
    assert access["route"] == "/api/v1/me"
    assert access["status"] == 200
    assert isinstance(access["duration_ms"], int | float) and access["duration_ms"] >= 0
    assert all(r["tenant_id"] == str(seeded.id) for r in mine if r.get("tenant_id"))


def test_anonymous_request_log_has_a_request_id_but_no_tenant(
    json_log_api: ApiFactory, capsys: pytest.CaptureFixture[str]
) -> None:
    capsys.readouterr()
    resp = json_log_api.anonymous().get("/me", headers={"X-Request-ID": "req-observ-00002"})
    assert resp.status_code == 401
    mine = [
        r for r in log_lines(capsys.readouterr().out) if r.get("request_id") == "req-observ-00002"
    ]
    assert mine and not any(r.get("tenant_id") for r in mine)
    assert next(r for r in mine if r.get("route"))["status"] == 401


def test_pii_is_masked_in_every_log_line_of_a_command(
    json_log_api: ApiFactory, seeded: SeededTenant, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seeded.admin
    client = json_log_api.login_as(seeded.admin)
    capsys.readouterr()
    body = new_user_body(
        email="very.private.person@example.test", mobile="+919876543210", name="Private Person"
    )
    assert client.post("/users", body).status_code in (200, 201)
    out = capsys.readouterr().out
    assert out
    for raw in ("+919876543210", "very.private.person", "Private Person"):
        assert raw not in out, f"{raw!r} leaked into logs"


def test_session_cookie_token_and_csrf_token_are_never_logged(
    json_log_api: ApiFactory, seeded: SeededTenant, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seeded.admin
    client = json_log_api.login_as(seeded.admin)
    client.get("/me")
    out = capsys.readouterr().out
    assert client.session_token and client.csrf_token
    assert client.session_token not in out and client.csrf_token not in out


def test_json_body_over_one_megabyte_is_rejected_with_413(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    huge = b'{"name": "' + b"x" * (2 * 1024 * 1024) + b'", "code": "BIG1"}'
    resp = admin.post("/plants", content=huge, headers={"Content-Type": "application/json"})
    assert resp.status_code == 413
    assert problem(resp)["code"] == "payload_too_large"


def test_request_with_a_json_body_just_under_the_limit_is_processed(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    admin = admin_client(api, seeded)
    resp = admin.post("/plants", {"name": "x" * 1000, "code": "OKSIZE"})
    assert resp.status_code in (200, 201)


def test_problem_responses_for_real_endpoints_carry_the_request_id_header_and_body(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    anonymous = api.anonymous().get("/me", headers={"X-Request-ID": "req-observ-00003"})
    assert anonymous.headers["x-request-id"] == "req-observ-00003"
    assert problem(anonymous)["request_id"] == "req-observ-00003"
    assert seeded.viewer
    forbidden = api.login_as(seeded.viewer).post("/plants", {"name": "x", "code": "ZZ1"})
    assert problem(forbidden)["code"] == "forbidden"
    invalid = admin_client(api, seeded).post("/plants", {"name": "", "code": "bad code"})
    body = problem(invalid)
    assert body["code"] == "validation_error" and {e["field"] for e in body["errors"]} >= {"code"}
    missing = admin_client(api, seeded).get("/definitely/not/here")
    assert problem(missing)["code"] == "not_found"
