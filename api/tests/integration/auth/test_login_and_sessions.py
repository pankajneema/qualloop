"""ADR-008 / API.md 1.2 / INV-SEC-04: login, opaque Redis sessions, cookie flags, expiry, logout, deactivation."""

import re
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import redis as redis_lib
import time_machine
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, SeededUser, create_user, fetch_all
from tests.factories.env import PASSWORD
from tests.integration.auth.helpers import (
    redis_keys,
    session_key,
    set_cookie_headers,
    strip_volatile,
)
from tests.integration.commands.test_command_audit_and_outbox import log_rows

pytestmark = pytest.mark.integration

IDLE = timedelta(hours=8)
ABSOLUTE = timedelta(days=7)


def test_login_succeeds_and_sets_session_and_csrf_cookies(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.quality
    client = api.anonymous()
    resp = client.login(seeded.quality)
    assert resp.status_code == 200, resp.text
    cookies = set_cookie_headers(resp)
    assert {"ql_session", "ql_csrf"} <= set(cookies)
    assert re.fullmatch(r"[A-Za-z0-9_-]{43}", client.session_token or ""), (
        "32 random bytes, base64url"
    )
    assert client.csrf_token and client.csrf_token != client.session_token
    assert "argon2" not in resp.text and (client.session_token or "") not in resp.text


def test_session_cookie_flags_secure_httponly_samesite(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    """INV-SEC-04."""
    assert seeded.admin
    cookies = set_cookie_headers(api.anonymous().login(seeded.admin))
    session = cookies["ql_session"]
    assert "httponly" in session
    assert "secure" in session
    assert "samesite=lax" in session
    assert "path=/" in session
    csrf = cookies["ql_csrf"]  # double-submit cookie must be readable by the page's JavaScript
    assert "httponly" not in csrf
    assert "secure" in csrf and "samesite=lax" in csrf and "path=/" in csrf


def test_session_is_an_opaque_redis_record_keyed_by_the_token_hash_with_an_eight_hour_idle_ttl(
    api: ApiFactory, seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    assert seeded.admin
    client = api.login_as(seeded.admin)
    token = client.session_token
    assert token
    key = session_key(token)
    assert redis_client.exists(key) == 1
    assert not redis_keys(redis_client, f"*{token}*"), "raw token must never be a Redis key"
    ttl = redis_client.ttl(key)
    assert int(IDLE.total_seconds()) - 120 < ttl <= int(IDLE.total_seconds())
    assert redis_client.exists(f"user_sessions:{seeded.admin.id}") == 1


@pytest.mark.parametrize("variant", ["upper", "lower", "padded"])
def test_login_email_is_case_insensitive(
    api: ApiFactory, seeded: SeededTenant, variant: str
) -> None:
    assert seeded.quality
    email = {
        "upper": seeded.quality.email.upper(),
        "lower": seeded.quality.email.lower(),
        "padded": f" {seeded.quality.email} ",
    }[variant]
    resp = api.anonymous().login(email)
    assert resp.status_code in (200, 401)
    if variant != "padded":
        assert resp.status_code == 200


def test_login_failures_return_one_generic_error_whatever_the_cause(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    """Unknown email, wrong password, inactive user and a user with no password are indistinguishable."""
    inactive = create_user(app_engine, seeded.id, active=False)
    no_password = create_user(app_engine, seeded.id, with_password=False)
    assert seeded.quality
    attempts = [
        api.anonymous("203.0.113.21").login(f"nobody.{uuid4().hex}@example.test"),
        api.anonymous("203.0.113.22").login(seeded.quality, password="wrong-password-123"),
        api.anonymous("203.0.113.23").login(inactive),
        api.anonymous("203.0.113.24").login(no_password, password="anything-at-all-1"),
    ]
    bodies = []
    for resp in attempts:
        assert resp.status_code == 401, resp.text
        assert "ql_session" not in set_cookie_headers(resp)
        bodies.append(strip_volatile(problem(resp)))
    assert all(b == bodies[0] for b in bodies), bodies
    assert bodies[0]["code"] == "unauthenticated"
    for leaked in (seeded.quality.email, "inactive", "no such"):
        assert leaked not in attempts[0].text.lower().replace("unauthenticated", "")


def test_login_runs_a_password_verification_even_when_there_is_nothing_to_verify_against(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Timing equalisation: unknown / inactive / password-less users still cost one argon2 verification."""
    argon2 = load("argon2")
    inactive = create_user(app_engine, seeded.id, active=False)
    no_password = create_user(app_engine, seeded.id, with_password=False)
    calls: list[str] = []
    real = argon2.PasswordHasher.verify

    def spy(self: Any, hash_: str, password: str) -> bool:
        calls.append(hash_)
        return bool(real(self, hash_, password))

    monkeypatch.setattr(argon2.PasswordHasher, "verify", spy)
    cases: list[SeededUser | str] = [f"ghost.{uuid4().hex}@example.test", inactive, no_password]
    for i, who in enumerate(cases):
        calls.clear()
        api.anonymous(f"203.0.113.{40 + i}").login(who, password="irrelevant-pass-1")
        assert len(calls) >= 1, f"no argon2 verification for case {i}"


def test_me_works_with_the_session_cookie_and_401_without(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.viewer
    client = api.login_as(seeded.viewer)
    assert client.get("/me").status_code == 200
    assert api.anonymous().get("/me").status_code == 401


@pytest.mark.parametrize("forged", ["", "x", "A" * 43, "A" * 200, "../../etc/passwd", "a b c"])
def test_forged_session_cookies_are_rejected(api: ApiFactory, forged: str) -> None:
    client = api.anonymous()
    client.http.cookies.set("ql_session", forged)
    resp = client.get("/me")
    assert resp.status_code == 401
    assert problem(resp)["code"] == "unauthenticated"


def test_supplier_cookie_is_not_accepted_on_internal_routes(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    client = api.anonymous()
    client.http.cookies.set("ql_sup", "tenant.session.signature")
    assert client.get("/me").status_code == 401
    assert client.get("/users").status_code == 401


def test_logout_deletes_the_server_side_session_and_clears_cookies(
    api: ApiFactory, seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    assert seeded.admin
    client = api.login_as(seeded.admin)
    token = client.session_token
    assert token
    resp = client.post("/auth/logout")
    assert resp.status_code in (200, 204), resp.text
    assert redis_client.exists(session_key(token)) == 0
    cleared = set_cookie_headers(resp)["ql_session"]
    assert "max-age=0" in cleared or "expires=" in cleared
    client.http.cookies.set("ql_session", token)  # replaying the old token must not work
    assert client.get("/me").status_code == 401


def test_logout_only_ends_the_calling_session(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.admin
    first, second = api.login_as(seeded.admin), api.login_as(seeded.admin)
    first.post("/auth/logout")
    assert second.get("/me").status_code == 200


def test_deactivating_a_user_rejects_all_their_existing_sessions_immediately(
    api: ApiFactory, seeded: SeededTenant, redis_client: redis_lib.Redis, app_engine: Engine
) -> None:
    assert seeded.quality
    laptop, phone = api.login_as(seeded.quality), api.login_as(seeded.quality, ip="203.0.113.55")
    tokens = [laptop.session_token, phone.session_token]
    assert laptop.get("/me").status_code == phone.get("/me").status_code == 200
    admin = api.login_as(seeded.admin) if seeded.admin else None
    assert admin
    resp = admin.post(f"/users/{seeded.quality.id}/deactivate", {"reason": "Left the company"})
    assert resp.status_code == 200, resp.text
    assert laptop.get("/me").status_code == 401
    assert phone.get("/me").status_code == 401
    assert all(t and redis_client.exists(session_key(t)) == 0 for t in tokens)
    assert redis_client.exists(f"user_sessions:{seeded.quality.id}") == 0
    row = fetch_all(
        app_engine, seeded.id, "SELECT active FROM users WHERE id = :i", {"i": seeded.quality.id}
    )
    assert row[0]["active"] is False


def test_deactivating_one_user_does_not_end_other_users_sessions(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.quality and seeded.viewer and seeded.admin
    viewer = api.login_as(seeded.viewer)
    api.login_as(seeded.admin).post(f"/users/{seeded.quality.id}/deactivate", {"reason": "Left"})
    assert viewer.get("/me").status_code == 200


def test_deactivated_user_cannot_log_in_again(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.quality and seeded.admin
    api.login_as(seeded.admin).post(f"/users/{seeded.quality.id}/deactivate", {"reason": "Left"})
    assert api.anonymous("203.0.113.77").login(seeded.quality).status_code == 401


def _me_status(client: ApiClient, token: str) -> int:
    """GET /me presenting exactly this token, so the client's cookie-jar expiry rules cannot interfere
    with what the server decides about the session."""
    client.http.cookies.clear()
    client.http.cookies.set("ql_session", token)
    return client.get("/me").status_code


def test_a_session_is_rejected_after_eight_hours_without_activity(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.viewer
    active, idle = api.login_as(seeded.viewer), api.login_as(seeded.viewer)
    active_token, idle_token = active.session_token, idle.session_token
    assert active_token and idle_token
    start = datetime.now(UTC)
    with time_machine.travel(start + IDLE - timedelta(minutes=1), tick=False):
        assert _me_status(active, active_token) == 200  # just inside the idle window
    with time_machine.travel(start + IDLE + timedelta(seconds=5), tick=False):
        resp_status = _me_status(idle, idle_token)
        idle.http.cookies.clear()
        idle.http.cookies.set("ql_session", idle_token)
        body = idle.get("/me")
    assert resp_status == 401
    assert problem(body)["code"] == "unauthenticated"


def test_activity_slides_the_idle_window(api: ApiFactory, seeded: SeededTenant) -> None:
    assert seeded.viewer
    client = api.login_as(seeded.viewer)
    token = client.session_token
    assert token
    start = datetime.now(UTC)
    for hours in (7, 14, 21):  # each step is inside 8 h of the previous request
        with time_machine.travel(start + timedelta(hours=hours), tick=False):
            assert _me_status(client, token) == 200, f"expired at +{hours}h"


def test_a_session_is_rejected_after_seven_days_even_if_continuously_active(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.viewer
    client = api.login_as(seeded.viewer)
    token = client.session_token
    assert token
    start = datetime.now(UTC)
    for step in range(1, 24):  # every 7 h up to 161 h: always within the idle window
        with time_machine.travel(start + timedelta(hours=7 * step), tick=False):
            assert _me_status(client, token) == 200, f"expired early at +{7 * step}h"
    with time_machine.travel(start + ABSOLUTE + timedelta(minutes=1), tick=False):
        assert _me_status(client, token) == 401  # 7 h after the last request, but past the cap


def test_login_cookies_and_session_are_replaced_on_each_login(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    one, two = api.login_as(seeded.admin), api.login_as(seeded.admin)
    assert one.session_token != two.session_token
    assert one.csrf_token != two.csrf_token


def test_session_start_is_recorded_in_the_audit_log(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    api.login_as(seeded.admin)
    assert [r["action"] for r in log_rows(app_engine, seeded.id, seeded.admin.id)].count(
        "auth.login"
    ) == 1


def test_password_is_never_logged_or_echoed(
    api: ApiFactory, seeded: SeededTenant, capsys: pytest.CaptureFixture[str]
) -> None:
    assert seeded.admin
    api.anonymous().login(seeded.admin, password=PASSWORD)
    api.anonymous("203.0.113.88").login(seeded.admin, password="Wrong-Pass-Phrase-9")
    out = capsys.readouterr().out
    assert PASSWORD not in out
    assert "Wrong-Pass-Phrase-9" not in out


def test_failed_deactivation_does_not_end_the_users_sessions(
    api: ApiFactory, seeded: SeededTenant, owner_engine: Engine
) -> None:
    """Sessions are only killed once the deactivation has committed: a rolled-back command logs nobody out."""
    from tests.integration.commands.test_command_audit_and_outbox import failing_insert

    assert seeded.quality and seeded.admin
    victim = api.login_as(seeded.quality)
    admin = api.login_as(seeded.admin)
    with failing_insert(owner_engine, "outbox_events", seeded.id):
        resp = admin.post(f"/users/{seeded.quality.id}/deactivate", {"reason": "Left"})
    assert not 200 <= resp.status_code < 300
    assert victim.get("/me").status_code == 200
