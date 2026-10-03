"""P01 contract items 1 and 2 (security review): the client IP behind a trusted proxy, and the 5-failure login limit
under concurrency.

Contract (docs/build/phases/P01-test-contract.md section 5): `QL_TRUSTED_PROXIES` is a comma-separated CIDR list, default
empty. When the socket peer is inside a trusted CIDR the client IP is the right-most `X-Forwarded-For` entry that is not
itself trusted; otherwise the peer is used and `X-Forwarded-For` is ignored."""

import threading
from collections.abc import Iterator
from typing import Any, cast
from uuid import UUID, uuid4

import httpx
import pytest
import redis as redis_lib
from sqlalchemy import Engine

from app.core.config import get_settings
from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.env import API, PASSWORD, origin
from tests.integration.commands.test_command_audit_and_outbox import log_rows

pytestmark = pytest.mark.integration

TRUSTED_CIDRS = "10.0.0.0/8,192.168.50.0/24"
PROXY_PEER = "10.0.0.5"  # inside the trusted CIDRs
OTHER_PROXY = "192.168.50.9"  # a second trusted hop
CLIENT_A = "198.51.100.7"
CLIENT_B = "198.51.100.8"
UNTRUSTED_PEER = "203.0.113.55"


def login_via(
    client: ApiClient, email: str, password: str, forwarded_for: str | None
) -> httpx.Response:
    headers = {"Origin": origin()}
    if forwarded_for is not None:
        headers["X-Forwarded-For"] = forwarded_for
    return cast(
        httpx.Response,
        client.http.post(
            f"{API}/auth/login", json={"email": email, "password": password}, headers=headers
        ),
    )


def ghost() -> str:
    return f"ghost.{uuid4().hex}@example.test"


def login_ip(engine: Engine, tenant: UUID, user_id: UUID) -> str:
    rows = [r for r in log_rows(engine, tenant, user_id) if r["action"] == "auth.login"]
    assert rows, "no auth.login audit row"
    return str(rows[-1]["ip"])


@pytest.fixture
def behind_proxy(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Set before the app fixture builds the app, so settings are read with the proxy list in place."""
    monkeypatch.setenv("QL_TRUSTED_PROXIES", TRUSTED_CIDRS)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# --- item 1: trusted peer ---------------------------------------------------------------------------
def test_two_clients_behind_a_trusted_proxy_have_separate_per_ip_login_counters(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    proxy = api.anonymous(PROXY_PEER)
    for _ in range(5):  # five different unknown emails: only the per-IP counter can trip
        assert login_via(proxy, ghost(), "wrong-password-1", CLIENT_A).status_code == 401
    blocked = login_via(proxy, ghost(), "wrong-password-1", CLIENT_A)
    assert blocked.status_code == 429, "client A is locked out"
    assert problem(blocked)["code"] == "rate_limited"
    other = login_via(proxy, seeded.admin.email, PASSWORD, CLIENT_B)
    assert other.status_code == 200, f"client B must not share A's counter: {other.status_code}"


def test_one_client_behind_a_trusted_proxy_is_not_locked_out_by_everyone_elses_failures(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant
) -> None:
    """The reported bug: 5 bad logins from five different users through one proxy used to lock everybody out."""
    assert seeded.quality
    proxy = api.anonymous(PROXY_PEER)
    for i in range(5):
        client_ip = f"198.51.100.{100 + i}"
        assert login_via(proxy, ghost(), "wrong-password-1", client_ip).status_code == 401
    bystander = login_via(proxy, seeded.quality.email, PASSWORD, "198.51.100.200")
    assert bystander.status_code == 200, bystander.text


def test_activity_log_ip_is_the_forwarded_client_not_the_proxy(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    proxy = api.anonymous(PROXY_PEER)
    assert login_via(proxy, seeded.admin.email, PASSWORD, CLIENT_B).status_code == 200
    assert login_ip(app_engine, seeded.id, seeded.admin.id) == CLIENT_B
    token = proxy.csrf_token
    created = proxy.http.post(
        f"{API}/plants",
        json={"name": "Behind proxy", "code": f"P{uuid4().hex[:5].upper()}"},
        headers={"Origin": origin(), "X-CSRF-Token": token or "", "X-Forwarded-For": CLIENT_B},
    )
    assert created.status_code in (200, 201), created.text
    rows = fetch_all(
        app_engine,
        seeded.id,
        "SELECT ip FROM activity_log WHERE object_id = :o",
        {"o": UUID(created.json()["id"])},
    )
    assert [str(r["ip"]) for r in rows] == [CLIENT_B], "command audit rows record the client too"


def test_the_client_is_the_rightmost_forwarded_entry_that_is_not_a_trusted_proxy(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    """`spoofed, real client, second proxy`: the attacker controls the left, the trusted proxies append on the right."""
    assert seeded.admin
    proxy = api.anonymous(PROXY_PEER)
    chain = f"192.0.2.99, {CLIENT_A}, {OTHER_PROXY}"
    assert login_via(proxy, seeded.admin.email, PASSWORD, chain).status_code == 200
    assert login_ip(app_engine, seeded.id, seeded.admin.id) == CLIENT_A


def test_a_forged_left_hand_entry_does_not_dodge_the_per_ip_limit_behind_a_trusted_proxy(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    proxy = api.anonymous(PROXY_PEER)
    for i in range(5):  # same real client, a different forged first entry each time
        assert (
            login_via(
                proxy, ghost(), "wrong-password-1", f"192.0.2.{i + 1}, {CLIENT_A}"
            ).status_code
            == 401
        )
    assert (
        login_via(proxy, seeded.admin.email, PASSWORD, f"192.0.2.77, {CLIENT_A}").status_code == 429
    )


def test_a_trusted_peer_without_a_forwarded_header_is_counted_as_itself(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    proxy = api.anonymous(PROXY_PEER)
    assert login_via(proxy, seeded.admin.email, PASSWORD, None).status_code == 200
    assert login_ip(app_engine, seeded.id, seeded.admin.id) == PROXY_PEER


# --- item 1: untrusted peer -------------------------------------------------------------------------
def test_a_forged_forwarded_header_from_an_untrusted_peer_is_ignored_for_rate_limiting(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    attacker = api.anonymous(UNTRUSTED_PEER)
    for i in range(5):  # the attacker invents a new "client" each time to reset a per-IP counter
        assert (
            login_via(attacker, ghost(), "wrong-password-1", f"198.51.100.{i + 10}").status_code
            == 401
        )
    sixth = login_via(attacker, seeded.admin.email, PASSWORD, "198.51.100.250")
    assert sixth.status_code == 429, "the peer's own counter must apply, whatever XFF claims"


def test_a_forged_forwarded_header_from_an_untrusted_peer_is_not_written_to_the_audit_log(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.admin
    attacker = api.anonymous(UNTRUSTED_PEER)
    assert login_via(attacker, seeded.admin.email, PASSWORD, "198.51.100.77").status_code == 200
    assert login_ip(app_engine, seeded.id, seeded.admin.id) == UNTRUSTED_PEER


def test_by_default_no_proxy_is_trusted_so_forwarded_headers_are_ignored(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine
) -> None:
    """QL_TRUSTED_PROXIES is empty by default: even a 10.x peer is just a peer."""
    assert seeded.admin
    assert get_settings().model_dump().get("trusted_proxies") in ("", [], (), None)
    client = api.anonymous(PROXY_PEER)
    for i in range(5):
        assert (
            login_via(client, ghost(), "wrong-password-1", f"198.51.100.{i + 30}").status_code
            == 401
        )
    assert login_via(client, seeded.admin.email, PASSWORD, "198.51.100.99").status_code == 429


def test_a_malformed_forwarded_entry_from_a_trusted_peer_never_causes_a_server_error(
    behind_proxy: None, api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.admin
    proxy = api.anonymous(PROXY_PEER)
    for value in ("not-an-ip", ",,,", "   ", "999.1.1.1", "198.51.100.7:8080"):
        resp = login_via(proxy, seeded.admin.email, "wrong-password-1", value)
        assert resp.status_code in (401, 429), f"X-Forwarded-For={value!r}: {resp.status_code}"


# --- item 2: concurrent wrong-password logins -------------------------------------------------------
def test_ten_concurrent_wrong_password_logins_cannot_exceed_the_five_failure_limit(
    api: ApiFactory, seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    """Check-then-record race: every request used to pass the 'blocked?' check before any of them recorded."""
    assert seeded.quality
    attempts = 10
    clients = [
        api.anonymous(f"203.0.113.{150 + i}") for i in range(attempts)
    ]  # per-IP counters can't trip
    barrier = threading.Barrier(attempts, timeout=30)
    results: list[httpx.Response | BaseException] = [RuntimeError("did not run")] * attempts

    def attempt(index: int) -> None:
        try:
            barrier.wait()
            assert seeded.quality
            results[index] = clients[index].login(
                seeded.quality, password=f"wrong-password-{index}"
            )
        except BaseException as exc:
            results[index] = exc

    threads = [threading.Thread(target=attempt, args=(i,)) for i in range(attempts)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    errors = [r for r in results if isinstance(r, BaseException)]
    assert not errors, errors
    responses: list[Any] = [r for r in results if isinstance(r, httpx.Response)]
    statuses = sorted(r.status_code for r in responses)
    assert set(statuses) <= {401, 429}, statuses
    not_limited = [r for r in responses if r.status_code != 429]
    assert len(not_limited) <= 5, (
        f"{len(not_limited)} wrong-password attempts got through: {statuses}"
    )
    limited = [r for r in responses if r.status_code == 429]
    assert len(limited) >= attempts - 5
    for resp in limited:
        assert problem(resp)["code"] == "rate_limited"
        assert int(resp.headers["retry-after"]) > 0
    # and the account really is locked for the correct password
    assert (
        api.anonymous("203.0.113.199").login(seeded.quality, password=PASSWORD).status_code == 429
    )
