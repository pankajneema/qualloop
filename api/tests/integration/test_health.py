import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.integration


def test_healthz_200(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_readyz_200_when_deps_up(client: TestClient) -> None:
    resp = client.get("/readyz")
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "status": "ready",
        "checks": {"db": "ok", "redis": "ok", "migrations": "ok"},
    }


def test_readyz_503_when_redis_down(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import get_settings

    monkeypatch.setenv("QL_REDIS_URL", "redis://127.0.0.1:1/0")
    get_settings.cache_clear()
    resp = client.get("/readyz")
    assert resp.status_code == 503
    body = resp.json()
    assert body["checks"]["redis"] == "fail"
    assert body["checks"]["db"] == "ok"
    assert "127.0.0.1" not in resp.text  # no connection strings leaked
