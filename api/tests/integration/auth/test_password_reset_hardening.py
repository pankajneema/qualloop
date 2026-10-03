"""P01 contract item 14 (security review): password-reset one-time codes.

(a) a redelivered OLDER job must not replace the newest emailed code; (b) an expired code never leaves a key without TTL;
(c) per-account cap on failed confirms that a new request does not reset; (d) per-IP limits on request and confirm
(20 per hour each, SPEC-GAP pending in the contract); (e) a broker failure does not change the 202 answer."""

import json
from datetime import datetime
from typing import Any
from uuid import uuid4

import pytest
import redis as redis_lib

from app.core import redis_client as redis_client_module
from tests.factories import mail
from tests.factories.api import ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.factories.jobs import declared_queues, running_worker, wait_idle
from tests.factories.redis_chaos import ChaosRedis, key_command
from tests.integration.auth.helpers import OTP_RE, strip_volatile
from tests.integration.auth.test_password_reset import (
    NEW_PASSWORD,
    OK,
    confirm_reset,
    request_reset,
)

pytestmark = pytest.mark.integration

IP_LIMIT = 20  # per IP per hour, for each of request and confirm (contract section 5)
ACCOUNT_FAILURE_CAP = 10  # failed confirms per account per 24 h


def ghost() -> str:
    return f"ghost.{uuid4().hex}@example.test"


def drain_jobs() -> None:
    broker = load("app.worker", "broker")
    queues = declared_queues(broker)
    with running_worker(broker, queues) as running:
        wait_idle(broker, running, queues)


def emails_with_codes(address: str) -> dict[str, str]:
    """idempotency key header -> 6-digit code, for every email delivered to `address`."""
    found: dict[str, str] = {}
    for message in mail.messages_to(address):
        headers = {k.lower(): v for k, v in mail.headers(message["ID"]).items()}
        codes = OTP_RE.findall(mail.body_text(message["ID"]))
        assert len(codes) == 1
        found[headers["x-idempotency-key"][0]] = str(codes[0])
    return found


def newest_code(address: str) -> str:
    messages = mail.messages_to(address)
    assert messages, f"no email for {address}"
    newest = max(
        messages, key=lambda m: datetime.fromisoformat(m["Created"].replace("Z", "+00:00"))
    )
    return str(OTP_RE.findall(mail.body_text(newest["ID"]))[0])


# --- (a) redelivery of an older job ----------------------------------------------------------------
def test_a_redelivered_older_reset_job_does_not_overwrite_the_newest_emailed_code(
    api: ApiFactory,
    seeded: SeededTenant,
    mailbox: None,
    redis_client: redis_lib.Redis,
) -> None:
    assert seeded.quality
    queue = load("app.core.auth.job_refs", "SEND_PASSWORD_RESET").queue
    request_reset(api.anonymous("203.0.113.61"), seeded.quality.email)
    request_reset(api.anonymous("203.0.113.62"), seeded.quality.email)
    queued: list[dict[str, Any]] = [
        json.loads(raw) for raw in redis_client.hvals(f"dramatiq:{queue}.msgs")
    ]
    mine = sorted(
        (m for m in queued if m["kwargs"].get("user_id") == str(seeded.quality.id)),
        key=lambda m: m["message_timestamp"],
    )
    assert len(mine) == 2, "two reset requests must queue two jobs"
    older, newer = mine
    older_nonce, newer_nonce = older["kwargs"]["request_nonce"], newer["kwargs"]["request_nonce"]

    drain_jobs()  # both jobs run once, in whatever order the worker threads pick them

    by_key = emails_with_codes(seeded.quality.email)
    newest_email_code = next(
        (code for key, code in by_key.items() if key.startswith(f"{newer_nonce}:")), None
    )
    assert newest_email_code, "the newest request must always be emailed"
    broker = load("app.worker", "broker")
    broker.enqueue(
        load("dramatiq", "Message").decode(json.dumps(older).encode())
    )  # redelivery of the OLD job
    drain_jobs()

    assert older_nonce != newer_nonce
    resp = confirm_reset(api.anonymous("203.0.113.63"), seeded.quality.email, newest_email_code)
    assert resp.status_code in OK, (
        "the newest emailed code stopped working after an old job was redelivered"
    )
    assert (
        api.anonymous("203.0.113.64").login(seeded.quality.email, NEW_PASSWORD).status_code == 200
    )


def test_the_older_code_does_not_work_once_a_newer_one_was_emailed(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    assert seeded.quality
    request_reset(api.anonymous("203.0.113.65"), seeded.quality.email)
    drain_jobs()
    first = newest_code(seeded.quality.email)
    request_reset(api.anonymous("203.0.113.66"), seeded.quality.email)
    drain_jobs()
    second = newest_code(seeded.quality.email)
    assert first != second
    stale = confirm_reset(api.anonymous("203.0.113.67"), seeded.quality.email, first)
    assert 400 <= stale.status_code < 500
    assert (
        confirm_reset(api.anonymous("203.0.113.68"), seeded.quality.email, second).status_code in OK
    )


# --- (b) expiry race -------------------------------------------------------------------------------
def test_consume_after_the_code_expired_does_not_leave_an_otp_key_without_a_ttl(
    redis_client: redis_lib.Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    otp = load("app.core.auth.otp")
    user_id = uuid4()
    key = f"otp:pwreset:{user_id}"
    otp.store(user_id, "123456")
    assert redis_client.ttl(key) > 0
    chaos = ChaosRedis.sharing(redis_client)

    def expire() -> None:  # the TTL fires right after the first touch
        redis_client.delete(key)

    chaos.arm(key_command(key), expire)
    monkeypatch.setattr(redis_client_module, "_client_for", lambda _url: chaos)

    assert otp.consume(user_id, "123456") in (True, False)

    assert chaos.fired_by is not None, "consume never touched the key"
    assert redis_client.ttl(key) != -1, "a stray otp key with no expiry was left behind"
    assert redis_client.hget(key, "attempts") is None or redis_client.ttl(key) > 0


def test_consume_of_an_expired_code_creates_nothing_in_redis(redis_client: redis_lib.Redis) -> None:
    otp = load("app.core.auth.otp")
    user_id = uuid4()
    assert otp.consume(user_id, "123456") is False
    assert redis_client.exists(f"otp:pwreset:{user_id}") == 0


# --- (c) per-account failure cap -------------------------------------------------------------------
def test_after_ten_failed_confirms_in_a_day_even_a_fresh_valid_code_is_refused(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    assert seeded.quality
    email = seeded.quality.email
    ip = iter(
        f"198.51.100.{n}" for n in range(1, 250)
    )  # a new IP each call: only the account cap can bite
    for _ in range(2):  # two codes, five wrong guesses each = ten failures
        request_reset(api.anonymous(next(ip)), email)
        drain_jobs()
        real = newest_code(email)
        wrong = "000000" if real != "000000" else "111111"
        for _ in range(5):
            assert 400 <= confirm_reset(api.anonymous(next(ip)), email, wrong).status_code < 500
    request_reset(api.anonymous(next(ip)), email)  # the third request of the hour: allowed
    drain_jobs()
    fresh = newest_code(email)

    resp = confirm_reset(api.anonymous(next(ip)), email, fresh)

    assert 400 <= resp.status_code < 500, "a valid code worked after the per-account failure cap"
    assert api.anonymous(next(ip)).login(email, NEW_PASSWORD).status_code == 401
    assert api.anonymous(next(ip)).login(email).status_code == 200, "password unchanged"


def test_failures_below_the_account_cap_do_not_block_a_valid_code(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    assert seeded.quality
    email = seeded.quality.email
    request_reset(api.anonymous("198.51.100.201"), email)
    drain_jobs()
    real = newest_code(email)
    wrong = "000000" if real != "000000" else "111111"
    for i in range(4):
        confirm_reset(api.anonymous(f"198.51.100.{210 + i}"), email, wrong)
    assert confirm_reset(api.anonymous("198.51.100.220"), email, real).status_code in OK


def test_junk_confirms_with_no_code_issued_do_not_block_the_later_real_code(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    """Security review M-1: the account cap counts only failed guesses against an issued, live code."""
    assert seeded.quality
    email = seeded.quality.email
    for i in range(ACCOUNT_FAILURE_CAP + 2):  # no code exists yet; a new IP each time
        junk = confirm_reset(api.anonymous(f"192.0.2.{10 + i}"), email, f"{i:06d}")
        assert 400 <= junk.status_code < 500 and junk.status_code != 429
    request_reset(api.anonymous("192.0.2.100"), email)
    drain_jobs()
    real = newest_code(email)

    resp = confirm_reset(api.anonymous("192.0.2.101"), email, real)

    assert resp.status_code == 202, (
        "junk confirms with no code issued denied the real owner recovery"
    )
    assert api.anonymous("192.0.2.102").login(email, NEW_PASSWORD).status_code == 200


def test_ten_wrong_guesses_against_a_live_code_still_block_a_later_fresh_valid_code(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    """Pairs with M-1: junk before any code must not count, but real guesses against live codes do."""
    assert seeded.quality
    email = seeded.quality.email
    for i in range(3):  # junk with no code: must not count towards the cap
        confirm_reset(api.anonymous(f"192.0.2.{110 + i}"), email, "123123")
    ip = iter(f"192.0.2.{120 + n}" for n in range(120))
    for _ in range(2):  # 2 live codes x 5 wrong guesses = 10 counted failures
        request_reset(api.anonymous(next(ip)), email)
        drain_jobs()
        real = newest_code(email)
        wrong = "000000" if real != "000000" else "111111"
        for _ in range(5):
            assert 400 <= confirm_reset(api.anonymous(next(ip)), email, wrong).status_code < 500
    request_reset(api.anonymous(next(ip)), email)
    drain_jobs()
    fresh = newest_code(email)

    resp = confirm_reset(api.anonymous(next(ip)), email, fresh)

    assert 400 <= resp.status_code < 500
    assert api.anonymous(next(ip)).login(email, NEW_PASSWORD).status_code == 401


def test_confirm_with_no_live_code_answers_the_same_generic_422_as_a_wrong_code(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    assert seeded.quality
    email = seeded.quality.email
    no_code = confirm_reset(api.anonymous("192.0.2.240"), email, "424242")
    request_reset(api.anonymous("192.0.2.241"), email)
    drain_jobs()
    real = newest_code(email)
    wrong = "000000" if real != "000000" else "111111"
    wrong_resp = confirm_reset(api.anonymous("192.0.2.242"), email, wrong)

    assert no_code.status_code == 422 == wrong_resp.status_code
    assert strip_volatile(problem(no_code)) == strip_volatile(problem(wrong_resp))


# --- (d) per-IP limits -----------------------------------------------------------------------------
def test_reset_request_is_limited_per_ip_with_retry_after(api: ApiFactory) -> None:
    attacker = api.anonymous("203.0.113.71")
    for i in range(
        IP_LIMIT
    ):  # a different (unknown) email each time, so the per-email limit never trips
        assert request_reset(attacker, ghost()).status_code in OK, f"request {i + 1}"
    blocked = request_reset(attacker, ghost())
    assert blocked.status_code == 429, blocked.text
    assert problem(blocked)["code"] == "rate_limited"
    assert 0 < int(blocked.headers["retry-after"]) <= 3600
    assert request_reset(api.anonymous("203.0.113.72"), ghost()).status_code in OK


def test_reset_confirm_is_limited_per_ip_with_retry_after(api: ApiFactory) -> None:
    attacker = api.anonymous("203.0.113.73")
    for i in range(IP_LIMIT):
        resp = confirm_reset(attacker, ghost(), "000000")
        assert 400 <= resp.status_code < 500 and resp.status_code != 429, f"confirm {i + 1}"
    blocked = confirm_reset(attacker, ghost(), "000000")
    assert blocked.status_code == 429, blocked.text
    assert problem(blocked)["code"] == "rate_limited"
    assert 0 < int(blocked.headers["retry-after"]) <= 3600
    other = confirm_reset(api.anonymous("203.0.113.74"), ghost(), "000000")
    assert other.status_code != 429


def test_the_per_ip_reset_counters_hold_no_raw_ip_secret_or_email(
    api: ApiFactory, redis_client: redis_lib.Redis
) -> None:
    address = ghost()
    request_reset(api.anonymous("203.0.113.75"), address)
    keys = [str(k) for k in redis_client.scan_iter(match="rl:*", count=500)]
    assert keys and not any(address in k for k in keys)


# --- (e) enqueue failure ---------------------------------------------------------------------------
def test_reset_request_for_a_known_email_still_answers_202_when_the_job_cannot_be_enqueued(
    api: ApiFactory,
    seeded: SeededTenant,
    mailbox: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert seeded.quality
    reference = request_reset(
        api.anonymous("203.0.113.81"), ghost()
    )  # what an unknown email answers

    def broker_down(self: Any, message: Any, *, delay: Any = None) -> Any:
        raise redis_lib.ConnectionError("redis is down")

    monkeypatch.setattr("dramatiq.brokers.redis.RedisBroker.enqueue", broker_down)
    resp = request_reset(api.anonymous("203.0.113.82"), seeded.quality.email)

    assert resp.status_code == 202 == reference.status_code, resp.text
    assert resp.text == reference.text, "the answer must not reveal that the address exists"
    assert mail.messages_to(seeded.quality.email) == []
