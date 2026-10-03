"""API.md section 6 / ADR-008: login rate limit (5 failures / 15 min per email and per IP) and CSRF."""

from uuid import UUID, uuid4

import pytest
import redis as redis_lib
from sqlalchemy import Engine

from tests.factories.api import ApiFactory, problem
from tests.factories.db import SeededTenant, create_user, fetch_all
from tests.factories.env import PASSWORD, origin
from tests.integration.auth.helpers import redis_keys
from tests.integration.commands.test_platform_commands_api import new_plant_body

pytestmark = pytest.mark.integration

WINDOW_SECONDS = 15 * 60


def test_login_rate_limited(api: ApiFactory, seeded: SeededTenant) -> None:
    """INV-SEC-04: the sixth attempt after five failures is 429, even with the correct password."""
    assert seeded.quality
    client = api.anonymous("203.0.113.101")
    for attempt in range(5):
        resp = client.login(seeded.quality, password=f"wrong-password-{attempt}")
        assert resp.status_code == 401, f"attempt {attempt + 1}: {resp.text}"
    blocked = client.login(seeded.quality, password=PASSWORD)
    assert blocked.status_code == 429, blocked.text
    assert problem(blocked)["code"] == "rate_limited"
    assert 0 < int(blocked.headers["retry-after"]) <= WINDOW_SECONDS
    assert "ql_session" not in blocked.headers.get("set-cookie", "")


def test_unknown_emails_are_rate_limited_too_so_limits_cannot_enumerate_users(
    api: ApiFactory,
) -> None:
    ghost = f"ghost.{uuid4().hex}@example.test"
    client = api.anonymous("203.0.113.102")
    assert [client.login(ghost, password="x-wrong-pass-1").status_code for _ in range(5)] == [
        401
    ] * 5
    assert client.login(ghost, password="x-wrong-pass-1").status_code == 429


def test_limit_is_per_email_across_ip_addresses(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.quality
    for i in range(5):  # five different IPs: only the email counter can trip
        api.anonymous(f"203.0.113.{110 + i}").login(seeded.quality, password="wrong-password-1")
    elsewhere = api.anonymous("203.0.113.200").login(seeded.quality, password=PASSWORD)
    assert elsewhere.status_code == 429


def test_limit_is_per_ip_across_emails(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.admin
    attacker = api.anonymous("203.0.113.120")
    for _ in range(5):  # five different (unknown) emails from one IP
        attacker.login(f"ghost.{uuid4().hex}@example.test", password="wrong-password-1")
    assert attacker.login(seeded.admin, password=PASSWORD).status_code == 429
    assert api.anonymous("203.0.113.121").login(seeded.admin, password=PASSWORD).status_code == 200


def test_one_locked_email_does_not_lock_other_users_from_other_addresses(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    bystander = create_user(app_engine, seeded.id)
    for i in range(5):
        api.anonymous(f"203.0.113.{130 + i}").login(seeded.quality, password="wrong-password-1")
    assert api.anonymous("203.0.113.140").login(bystander).status_code == 200


def test_rate_limit_counters_live_in_redis_with_a_fifteen_minute_window(
    api: ApiFactory, seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    assert seeded.quality
    api.anonymous("203.0.113.150").login(seeded.quality, password="wrong-password-1")
    keys = redis_keys(redis_client, "rl:*")
    assert keys, "no rl:* counter written"
    for key in keys:
        ttl = redis_client.ttl(key)
        assert 0 < ttl <= WINDOW_SECONDS, f"{key} ttl={ttl}"
    assert not any(seeded.quality.email in k for k in keys), "raw email must not be a Redis key"


def test_successful_logins_below_the_limit_are_never_blocked(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.quality
    client = api.anonymous("203.0.113.160")
    for _ in range(8):
        assert client.login(seeded.quality).status_code == 200


# --- CSRF (double-submit cookie + Origin) -----------------------------------------------------------
def _plants(app_engine: Engine, tenant: UUID, code: str) -> int:
    return len(fetch_all(app_engine, tenant, "SELECT 1 FROM plants WHERE code = :c", {"c": code}))


def test_command_without_csrf_header_is_403_and_changes_nothing(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    body = new_plant_body()
    resp = admin.post("/plants", body, csrf=False)
    assert resp.status_code == 403, resp.text
    problem(resp)
    assert _plants(app_engine, seeded.id, body["code"]) == 0


def test_command_with_mismatched_csrf_token_is_403(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    body = new_plant_body()
    resp = admin.post("/plants", body, headers={"X-CSRF-Token": "A" * 43})
    assert resp.status_code == 403, resp.text
    assert _plants(app_engine, seeded.id, body["code"]) == 0


def test_command_from_a_foreign_origin_is_403_even_with_a_valid_csrf_token(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    body = new_plant_body()
    resp = admin.post("/plants", body, headers={"Origin": "https://evil.example"})
    assert resp.status_code == 403, resp.text
    assert _plants(app_engine, seeded.id, body["code"]) == 0


def test_command_with_matching_token_and_origin_succeeds(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    assert admin.csrf_token
    resp = admin.post("/plants", new_plant_body(), headers={"Origin": origin()})
    assert resp.status_code in (200, 201), resp.text


def test_csrf_token_of_another_session_is_rejected(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.admin and seeded.quality
    mine, theirs = api.login_as(seeded.admin), api.login_as(seeded.quality)
    resp = mine.post(
        "/plants", new_plant_body(), headers={"X-CSRF-Token": theirs.csrf_token or "x"}
    )
    assert resp.status_code == 403


def test_safe_methods_do_not_require_csrf(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    admin.http.headers.pop("X-CSRF-Token", None)
    assert admin.get("/me").status_code == 200
    assert admin.get("/plants").status_code == 200


def test_login_itself_needs_no_csrf_token(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.admin
    resp = api.anonymous().public_post(
        "/auth/login", {"email": seeded.admin.email, "password": PASSWORD}
    )
    assert resp.status_code == 200


def test_logout_requires_csrf(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.admin
    admin = api.login_as(seeded.admin)
    assert admin.post("/auth/logout", csrf=False).status_code == 403
    assert admin.get("/me").status_code == 200  # still logged in
