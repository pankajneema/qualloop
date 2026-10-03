"""PHASES P01 / ADR-008 / INV-PLT-11: password reset by email OTP, sent only by a worker, with an idempotency key.

Needs Postgres, Redis (db 15), mailpit and the P01 Dramatiq worker running in-process."""

import re
from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
import redis as redis_lib
from sqlalchemy import Engine

from tests.factories import mail
from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, create_user, fetch_all
from tests.factories.env import PASSWORD
from tests.factories.jobs import declared_queues, running_worker, wait_idle
from tests.integration.auth.helpers import OTP_RE, redis_keys, redis_values, strip_volatile

pytestmark = pytest.mark.integration

NEW_PASSWORD = "A-brand-new-Passphrase-77"
OK = (200, 202, 204)


@pytest.fixture
def worker(api: ApiFactory, mailbox: None) -> Iterator[tuple[Any, Any, set[str]]]:
    """The P01 worker (global broker, real actors) consuming every declared queue, in-process."""
    broker = load("app.worker", "broker")
    queues = declared_queues(broker)
    assert queues, "app.worker declares no queues"
    with running_worker(broker, queues) as running:
        yield broker, running, queues


def request_reset(client: ApiClient, email: str) -> Any:
    return client.public_post("/auth/password-reset/request", {"email": email})


def confirm_reset(client: ApiClient, email: str, otp: str, password: str = NEW_PASSWORD) -> Any:
    return client.public_post(
        "/auth/password-reset/confirm", {"email": email, "otp": otp, "new_password": password}
    )


def latest_otp(address: str) -> str:
    messages = mail.messages_to(address)
    assert messages, f"no email delivered to {address}"
    text = mail.body_text(messages[0]["ID"])
    codes = OTP_RE.findall(text)
    assert len(codes) == 1, f"expected exactly one 6-digit code in the email, got {codes}"
    return str(codes[0])


def deliver(worker: tuple[Any, Any, set[str]]) -> None:
    broker, running, queues = worker
    wait_idle(broker, running, queues)


def test_reset_request_sends_a_six_digit_otp_by_email_via_the_worker(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    resp = request_reset(api.anonymous(), seeded.quality.email)
    assert resp.status_code in OK, resp.text
    deliver(worker)
    messages = mail.messages_to(seeded.quality.email)
    assert len(messages) == 1
    assert re.fullmatch(r"\d{6}", latest_otp(seeded.quality.email))
    assert "reset" in messages[0]["Subject"].lower()


def test_the_api_request_itself_sends_nothing_external_only_the_worker_does(
    api: ApiFactory, seeded: SeededTenant, mailbox: None
) -> None:
    """INV-PLT-11: no worker running, so no email may exist after the request returns."""
    assert seeded.quality
    assert request_reset(api.anonymous(), seeded.quality.email).status_code in OK
    assert mail.messages_to(seeded.quality.email) == []
    broker = load("app.worker", "broker")
    queues = declared_queues(broker)
    with running_worker(broker, queues) as running:
        wait_idle(broker, running, queues)
    assert len(mail.messages_to(seeded.quality.email)) == 1  # the job was queued, not lost


def test_reset_email_carries_an_idempotency_key_header(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    message_id = mail.messages_to(seeded.quality.email)[0]["ID"]
    headers = {k.lower(): v for k, v in mail.headers(message_id).items()}
    assert headers["x-idempotency-key"] and headers["x-idempotency-key"][0]


def test_reset_request_is_indistinguishable_for_unknown_and_inactive_emails_and_sends_no_mail(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    inactive = create_user(app_engine, seeded.id, active=False)
    ghost = f"ghost.{uuid4().hex}@example.test"
    known = request_reset(api.anonymous("203.0.113.171"), seeded.quality.email)
    unknown = request_reset(api.anonymous("203.0.113.172"), ghost)
    dead = request_reset(api.anonymous("203.0.113.173"), inactive.email)
    deliver(worker)
    assert known.status_code == unknown.status_code == dead.status_code
    assert known.status_code in OK
    assert known.text == unknown.text == dead.text
    assert mail.messages_to(ghost) == [] and mail.messages_to(inactive.email) == []
    assert len(mail.messages_to(seeded.quality.email)) == 1


def test_otp_is_stored_hashed_with_a_fifteen_minute_ttl(
    api: ApiFactory,
    seeded: SeededTenant,
    worker: tuple[Any, Any, set[str]],
    redis_client: redis_lib.Redis,
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    otp = latest_otp(seeded.quality.email)
    keys = redis_keys(redis_client, "otp:*")
    assert keys, "no otp:* record"
    for key in keys:
        assert otp not in key
        assert not any(otp in value for value in redis_values(redis_client, key)), (
            "OTP stored in clear"
        )
        assert 0 < redis_client.ttl(key) <= 15 * 60


def test_reset_confirm_sets_the_new_argon2id_password_and_login_follows(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    otp = latest_otp(seeded.quality.email)
    resp = confirm_reset(api.anonymous(), seeded.quality.email, otp)
    assert resp.status_code in OK, resp.text
    row = fetch_all(
        app_engine,
        seeded.id,
        "SELECT password_hash FROM users WHERE id = :i",
        {"i": seeded.quality.id},
    )[0]
    assert row["password_hash"].startswith("$argon2id$")
    assert NEW_PASSWORD not in row["password_hash"]
    assert (
        api.anonymous("203.0.113.181").login(seeded.quality.email, NEW_PASSWORD).status_code == 200
    )
    assert api.anonymous("203.0.113.182").login(seeded.quality.email, PASSWORD).status_code == 401


def test_reset_confirm_emits_user_password_reset_and_audits_it(
    api: ApiFactory,
    seeded: SeededTenant,
    app_engine: Engine,
    clean_outbox: None,
    worker: tuple[Any, Any, set[str]],
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    confirm_reset(api.anonymous(), seeded.quality.email, latest_otp(seeded.quality.email))
    events = fetch_all(
        app_engine,
        seeded.id,
        "SELECT event_type, aggregate_id FROM outbox_events WHERE event_type = 'USER_PASSWORD_RESET'",
    )
    assert [(e["aggregate_id"]) for e in events] == [seeded.quality.id]
    audit = fetch_all(
        app_engine,
        seeded.id,
        "SELECT actor_type, object_type FROM activity_log WHERE object_id = :i AND action LIKE '%password%'",
        {"i": seeded.quality.id},
    )
    assert len(audit) == 1 and audit[0]["object_type"] == "user"


def test_first_password_of_an_admin_created_user_is_set_through_the_reset_flow(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.admin
    email = f"first.{uuid4().hex[:8]}@example.test"
    created = api.login_as(seeded.admin).post(
        "/users", {"email": email, "name": "First Timer", "role": "viewer"}
    )
    assert created.status_code in (200, 201), created.text
    assert (
        api.anonymous("203.0.113.191").login(email, NEW_PASSWORD).status_code == 401
    )  # no password yet
    request_reset(api.anonymous("203.0.113.192"), email)
    deliver(worker)
    assert confirm_reset(api.anonymous("203.0.113.193"), email, latest_otp(email)).status_code in OK
    assert api.anonymous("203.0.113.194").login(email, NEW_PASSWORD).status_code == 200


def test_otp_is_single_use(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    otp = latest_otp(seeded.quality.email)
    assert confirm_reset(api.anonymous(), seeded.quality.email, otp).status_code in OK
    again = confirm_reset(api.anonymous(), seeded.quality.email, otp, "Another-Fresh-Passphrase-1")
    assert 400 <= again.status_code < 500
    assert (
        api.anonymous("203.0.113.201").login(seeded.quality.email, NEW_PASSWORD).status_code == 200
    )


def test_wrong_otp_is_rejected_and_the_password_is_unchanged(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    real = latest_otp(seeded.quality.email)
    wrong = "000000" if real != "000000" else "111111"
    resp = confirm_reset(api.anonymous(), seeded.quality.email, wrong)
    assert 400 <= resp.status_code < 500 and resp.status_code != 429
    assert (
        api.anonymous("203.0.113.211").login(seeded.quality).status_code == 200
    )  # old password intact


def test_otp_is_burnt_after_five_wrong_attempts(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    client = api.anonymous("203.0.113.221")
    request_reset(client, seeded.quality.email)
    deliver(worker)
    real = latest_otp(seeded.quality.email)
    wrong = "000000" if real != "000000" else "111111"
    for _ in range(5):
        assert 400 <= confirm_reset(client, seeded.quality.email, wrong).status_code < 500
    burnt = confirm_reset(client, seeded.quality.email, real)
    assert 400 <= burnt.status_code < 500, "the correct OTP must not work after 5 failed attempts"
    assert (
        api.anonymous("203.0.113.222").login(seeded.quality.email, NEW_PASSWORD).status_code == 401
    )


def test_expired_otp_is_rejected_with_the_same_error_as_a_wrong_one(
    api: ApiFactory,
    seeded: SeededTenant,
    worker: tuple[Any, Any, set[str]],
    redis_client: redis_lib.Redis,
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    real = latest_otp(seeded.quality.email)
    wrong = "000000" if real != "000000" else "111111"
    wrong_resp = confirm_reset(api.anonymous("203.0.113.231"), seeded.quality.email, wrong)
    for key in redis_keys(redis_client, "otp:*"):  # what the 15-minute TTL does, done explicitly
        redis_client.delete(key)
    expired = confirm_reset(api.anonymous("203.0.113.232"), seeded.quality.email, real)
    assert expired.status_code == wrong_resp.status_code
    assert strip_volatile(problem(expired)) == strip_volatile(problem(wrong_resp))


def test_confirm_for_an_unknown_email_gives_the_same_error_as_a_wrong_otp(
    api: ApiFactory, seeded: SeededTenant, worker: tuple[Any, Any, set[str]]
) -> None:
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    deliver(worker)
    wrong = confirm_reset(api.anonymous("203.0.113.241"), seeded.quality.email, "000000")
    ghost = confirm_reset(
        api.anonymous("203.0.113.242"), f"ghost.{uuid4().hex}@example.test", "000000"
    )
    assert ghost.status_code == wrong.status_code
    assert strip_volatile(problem(ghost)) == strip_volatile(problem(wrong))


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"email": "a@b.test"},
        {"email": "a@b.test", "otp": "12345", "new_password": "x" * 20},
        {"email": "a@b.test", "otp": "abcdef", "new_password": "x" * 20},
    ],
    ids=["empty", "missing-otp", "short-otp", "non-digit-otp"],
)
def test_reset_confirm_validates_its_input(api: ApiFactory, body: dict[str, Any]) -> None:
    resp = api.anonymous().public_post("/auth/password-reset/confirm", body)
    assert resp.status_code == 422
    assert problem(resp)["code"] == "validation_error"


def test_reset_request_is_limited_to_three_per_hour_per_email(
    api: ApiFactory, seeded: SeededTenant
) -> None:
    assert seeded.quality
    client = api.anonymous("203.0.113.251")
    assert [request_reset(client, seeded.quality.email).status_code in OK for _ in range(3)] == [
        True
    ] * 3
    fourth = request_reset(client, seeded.quality.email)
    assert fourth.status_code == 429
    assert problem(fourth)["code"] == "rate_limited"
    assert 0 < int(fourth.headers["retry-after"]) <= 3600


def test_reset_request_limit_also_applies_to_unknown_emails(api: ApiFactory) -> None:
    ghost = f"ghost.{uuid4().hex}@example.test"
    client = api.anonymous("203.0.113.252")
    for _ in range(3):
        assert request_reset(client, ghost).status_code in OK
    assert request_reset(client, ghost).status_code == 429


def test_external_send_carries_idempotency_key(
    mailbox: None, redis_client: redis_lib.Redis
) -> None:
    """INV-PLT-11: the mail seam requires an idempotency key, stamps it on the message, and a second send with
    the same key is a no-op (a redelivered job must not double-send)."""
    import inspect

    send_email = load("app.core.mail", "send_email")
    parameter = inspect.signature(send_email).parameters["idempotency_key"]
    assert parameter.default is inspect.Parameter.empty, "idempotency_key must be required"
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    address = f"seam.{uuid4().hex[:8]}@example.test"
    key = f"evt-{uuid4()}:password_reset:{address}"
    send_email(to=address, subject="Probe", body="hello", idempotency_key=key)
    send_email(to=address, subject="Probe", body="hello", idempotency_key=key)
    assert len(mail.messages_to(address)) == 1
    headers = {k.lower(): v for k, v in mail.headers(mail.messages_to(address)[0]["ID"]).items()}
    assert headers["x-idempotency-key"] == [key]
    send_email(to=address, subject="Probe", body="hello", idempotency_key=key + "-other")
    assert len(mail.messages_to(address)) == 2


def test_password_reset_job_message_contains_ids_not_the_otp_or_email(
    api: ApiFactory, seeded: SeededTenant, redis_client: redis_lib.Redis
) -> None:
    """Queued messages sit in Redis: they carry tenant_id and user_id only, never the address or any secret."""
    assert seeded.quality
    request_reset(api.anonymous(), seeded.quality.email)
    queued = [
        value
        for key in redis_keys(redis_client, "dramatiq:*")
        for value in redis_values(redis_client, key)
    ]
    blob = " ".join(queued)
    assert str(seeded.id) in blob and str(seeded.quality.id) in blob, (
        "job carrying tenant_id/user_id not found"
    )
    assert seeded.quality.email not in blob


def test_password_stored_as_argon2id(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, worker: tuple[Any, Any, set[str]]
) -> None:
    """INV-SEC-04: argon2id with the library's default cost parameters (ADR-008), never the plaintext."""
    assert seeded.viewer
    request_reset(api.anonymous(), seeded.viewer.email)
    deliver(worker)
    confirm_reset(api.anonymous(), seeded.viewer.email, latest_otp(seeded.viewer.email))
    stored = fetch_all(
        app_engine,
        seeded.id,
        "SELECT password_hash FROM users WHERE id = :i",
        {"i": seeded.viewer.id},
    )[0]["password_hash"]
    assert stored.startswith("$argon2id$v=19$")
    assert NEW_PASSWORD not in stored
    assert load("argon2").PasswordHasher().check_needs_rehash(stored) is False
    assert load("argon2").PasswordHasher().verify(stored, NEW_PASSWORD)
