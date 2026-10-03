import json

import pytest
import structlog
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.logging import bind_request_context, clear_request_context, configure_logging
from app.main import create_app


def test_settings_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QL_LOG_LEVEL", "DEBUG")
    assert Settings().log_level == "DEBUG"


def test_healthz_is_pure_liveness() -> None:
    with TestClient(create_app()) as client:
        resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert resp.headers["x-request-id"]


def test_request_id_is_echoed_and_hostile_ids_replaced() -> None:
    with TestClient(create_app()) as client:
        good = client.get("/healthz", headers={"X-Request-ID": "abc12345-req"})
        bad = client.get("/healthz", headers={"X-Request-ID": "x injected log line"})
    assert good.headers["x-request-id"] == "abc12345-req"
    assert bad.headers["x-request-id"] != "x injected log line"


def test_log_lines_are_json_with_request_id(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging("INFO", "ci")
    bind_request_context("req-12345678", "tenant-a")
    try:
        structlog.get_logger().info("hello", extra_field=1)
    finally:
        clear_request_context()
    line = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert line["msg"] == "hello"
    assert line["request_id"] == "req-12345678"
    assert line["tenant_id"] == "tenant-a"
    assert line["level"] == "info"


def test_access_log_redacts_magic_link_token(capsys: pytest.CaptureFixture[str]) -> None:
    from fastapi import APIRouter

    app = create_app()
    router = APIRouter()

    @router.get("/s/{token}")
    def supplier_page(token: str) -> dict[str, str]:
        return {"ok": "1"}

    app.include_router(router)
    secret = "SECRETTOKEN0123456789"
    with TestClient(app) as client:
        client.get(f"/s/{secret}")  # matched route
        client.get(f"/supplier-access/{secret}/verify")  # unmatched
        client.get(f"/api/v1/nothing/{secret}")  # unmatched, token elsewhere
    out = capsys.readouterr().out
    assert secret not in out
    assert "/s/{token}" in out
    assert "<unmatched>" in out


def test_error_responses_carry_request_id() -> None:
    from fastapi import APIRouter

    app = create_app()
    router = APIRouter()

    @router.get("/boom")
    def boom() -> None:
        raise RuntimeError("boom")

    app.include_router(router)
    with TestClient(app, raise_server_exceptions=False) as client:
        not_found = client.get("/nope", headers={"X-Request-ID": "req-notfound-1"})
        server_error = client.get("/boom", headers={"X-Request-ID": "req-boom-0001"})
    assert not_found.status_code == 404
    assert not_found.headers["x-request-id"] == "req-notfound-1"
    assert server_error.status_code == 500
    assert server_error.headers["x-request-id"] == "req-boom-0001"


def test_docs_only_in_local(monkeypatch: pytest.MonkeyPatch) -> None:
    with TestClient(create_app()) as client:
        assert client.get("/openapi.json").status_code == 200
    monkeypatch.setenv("QL_ENV", "ci")
    monkeypatch.setenv("QL_DATABASE_URL", "postgresql+psycopg://a:b@db/x")
    monkeypatch.setenv("QL_DATABASE_URL_OWNER", "postgresql+psycopg://o:p@db/x")
    monkeypatch.setenv("QL_SESSION_SECRET", "s" * 32)
    monkeypatch.setenv("QL_HMAC_SECRET", "h" * 32)
    from app.core.config import get_settings

    get_settings.cache_clear()
    try:
        with TestClient(create_app()) as client:
            assert client.get("/openapi.json").status_code == 404
            assert client.get("/docs").status_code == 404
    finally:
        get_settings.cache_clear()


def test_startup_fails_outside_local_with_default_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from pydantic import ValidationError

    for var in ("QL_DATABASE_URL", "QL_SESSION_SECRET", "QL_HMAC_SECRET"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("QL_ENV", "production")
    with pytest.raises(ValidationError, match="unsafe default"):
        Settings()
    monkeypatch.setenv("QL_DATABASE_URL", "postgresql+psycopg://a:b@db/x")
    monkeypatch.setenv("QL_SESSION_SECRET", "short")
    monkeypatch.setenv("QL_HMAC_SECRET", "h" * 32)
    with pytest.raises(ValidationError, match="session_secret"):
        Settings()
    monkeypatch.setenv("QL_SESSION_SECRET", "s" * 32)
    # P01 contract items 7/8: outside local/ci the other dev placeholders are refused too, so a valid production
    # configuration also names real object-store keys and a Redis URL with credentials.
    monkeypatch.setenv("QL_S3_ACCESS_KEY", "prod-access-key-0001")
    monkeypatch.setenv("QL_S3_SECRET_KEY", "prod-secret-key-0000000000000001")
    monkeypatch.setenv("QL_REDIS_URL", "redis://qualloop_app:a-real-password@redis.internal:6379/0")
    assert Settings().env == "production"
