"""Blueprint 8 C2 "verify mobile (OTP)" and A-78 / A-110: 6 digits, 10 minute TTL, 5 attempts, 3 sends per hour per
contact. Email goes through the real SMTP path (mailpit); mobile goes through the dev fake channel until P05.
OTPs are sent by a worker only (INV-PLT-11) and are never stored or logged in clear."""

import re
from collections.abc import Iterator
from typing import Any
from uuid import UUID

import pytest
import redis as redis_lib
from sqlalchemy import Engine

from tests.factories import mail
from tests.factories.api import ApiClient, ApiFactory, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.jobs import declared_queues, running_worker, wait_idle
from tests.factories.masters import make_contact, make_supplier
from tests.integration.auth.helpers import OTP_RE, redis_keys, redis_values, strip_volatile
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration

OK = (200, 202, 204)


@pytest.fixture
def worker(api: ApiFactory, mailbox: None) -> Iterator[tuple[Any, Any, set[str]]]:
    """The platform worker (global broker, real actors) consuming every declared queue, in-process."""
    broker = load("app.worker", "broker")
    queues = declared_queues(broker)
    assert queues, "app.worker declares no queues"
    # ONE consumer thread: send jobs for the same contact are ordered by request nonce and an older job that runs after
    # a newer one is deliberately superseded (app.masters.otp.store). With two threads that order is a race, so the
    # count of delivered messages would vary between runs.
    with running_worker(broker, queues, threads=1) as running:
        yield broker, running, queues


@pytest.fixture(autouse=True)
def fake_channel() -> Iterator[list[dict[str, str]]]:
    sent: list[dict[str, str]] = load("app.masters.channels", "FAKE_SENT")
    sent.clear()
    yield sent
    sent.clear()


def deliver(worker: tuple[Any, Any, set[str]]) -> None:
    broker, running, queues = worker
    wait_idle(broker, running, queues)


def start(client: ApiClient, contact_id: str, channel: str) -> Any:
    return client.post(f"/contacts/{contact_id}/verify/start", {"channel": channel})


def confirm(client: ApiClient, contact_id: str, channel: str, code: str) -> Any:
    return client.post(f"/contacts/{contact_id}/verify/confirm", {"channel": channel, "code": code})


def code_sent(channel: str, contact: dict[str, Any], sent: list[dict[str, str]]) -> str:
    if channel == "email":
        messages = mail.messages_to(contact["email"])
        assert messages, f"no email delivered to {contact['email']}"
        body = mail.body_text(messages[0]["ID"])
    else:
        mine = [m for m in sent if m["to"] == contact["mobile"]]
        assert mine, f"the fake channel got nothing for {contact['mobile']}"
        body = mine[-1]["body"]
    codes = OTP_RE.findall(body)
    assert len(codes) == 1, f"expected exactly one 6-digit code, got {codes}"
    return str(codes[0])


def wrong(code: str) -> str:
    return "000000" if code != "000000" else "111111"


@pytest.fixture
def contact(quality: ApiClient) -> dict[str, Any]:
    return make_contact(quality, make_supplier(quality)["id"])


# --- sending ------------------------------------------------------------------------------------------------------
def test_the_api_request_sends_nothing_only_the_worker_does(
    quality: ApiClient, contact: dict[str, Any], fake_channel: list[dict[str, str]], mailbox: None
) -> None:
    """INV-PLT-11: no worker is running, so nothing external may exist once the request has returned."""
    for channel in ("email", "mobile"):
        assert start(quality, contact["id"], channel).status_code in OK
    assert fake_channel == [] and mail.messages_to(contact["email"]) == []


def test_verify_start_by_mobile_sends_one_six_digit_code_through_the_fake_channel(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    resp = start(quality, contact["id"], "mobile")
    assert resp.status_code in OK, resp.text
    deliver(worker)
    assert len(fake_channel) == 1 and fake_channel[0]["to"] == contact["mobile"]
    code = code_sent("mobile", contact, fake_channel)
    assert re.fullmatch(r"\d{6}", code)
    assert code not in resp.text, "the code never travels back in the API response"
    assert mail.messages_to(contact["email"]) == [], (
        "a mobile verification does not email the contact"
    )


def test_verify_start_by_email_sends_one_email_with_an_idempotency_header(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    assert start(quality, contact["id"], "email").status_code in OK
    deliver(worker)
    messages = mail.messages_to(contact["email"])
    assert len(messages) == 1 and fake_channel == []
    headers = mail.headers(messages[0]["ID"])
    assert any(k.lower() == "x-idempotency-key" for k in headers)
    assert re.fullmatch(r"\d{6}", code_sent("email", contact, fake_channel))


def test_otp_is_stored_hashed_with_a_ten_minute_ttl_and_no_raw_contact_details_in_the_key(
    quality: ApiClient,
    contact: dict[str, Any],
    worker: Any,
    fake_channel: list[dict[str, str]],
    redis_client: redis_lib.Redis,
) -> None:
    before = set(redis_keys(redis_client, "otp:*"))
    assert start(quality, contact["id"], "mobile").status_code in OK
    deliver(worker)
    code = code_sent("mobile", contact, fake_channel)
    new_keys = sorted(set(redis_keys(redis_client, "otp:*")) - before)
    assert new_keys, "an OTP must be stored server-side"
    for key in new_keys:
        assert 0 < redis_client.ttl(key) <= 10 * 60
        assert all(code not in v for v in redis_values(redis_client, key)), (
            "the code must be hashed"
        )
        assert contact["mobile"] not in key and contact["email"] not in key


# --- confirming ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("channel", "set_col", "other_col"),
    [
        ("mobile", "verified_mobile_at", "verified_email_at"),
        ("email", "verified_email_at", "verified_mobile_at"),
    ],
)
def test_confirming_the_right_code_marks_only_that_channel_verified(
    quality: ApiClient,
    seeded: SeededTenant,
    app_engine: Engine,
    contact: dict[str, Any],
    worker: Any,
    fake_channel: list[dict[str, str]],
    clean_outbox: None,
    channel: str,
    set_col: str,
    other_col: str,
) -> None:
    assert start(quality, contact["id"], channel).status_code in OK
    deliver(worker)
    code = code_sent(channel, contact, fake_channel)
    resp = confirm(quality, contact["id"], channel, code)
    assert resp.status_code in (200, 201), resp.text
    data = resp.json()
    assert data[set_col] is not None and data[other_col] is None
    stored = fetch_all(
        app_engine,
        seeded.id,
        "SELECT * FROM supplier_contacts WHERE id = :i",
        {"i": UUID(contact["id"])},
    )[0]
    assert stored[set_col] is not None and stored[other_col] is None
    if channel == "mobile":
        assert data["needs_reverification"] is False
    audit = [
        r for r in log_rows(app_engine, seeded.id, UUID(contact["id"])) if "verify" in r["action"]
    ]
    assert len(audit) == 1 and code not in str(audit[0])
    events = outbox_rows(app_engine, seeded.id, UUID(contact["id"]))
    assert [e["event_type"] for e in events].count("CONTACT_VERIFIED") == 1 and code not in str(
        events
    )


def test_a_code_cannot_be_used_twice(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    start(quality, contact["id"], "mobile")
    deliver(worker)
    code = code_sent("mobile", contact, fake_channel)
    assert confirm(quality, contact["id"], "mobile", code).status_code == 200
    again = confirm(quality, contact["id"], "mobile", code)
    assert again.status_code == 422 and problem(again)["code"] == "validation_error"


def test_wrong_expired_burnt_and_never_requested_codes_all_give_the_same_error(
    quality: ApiClient,
    contact: dict[str, Any],
    worker: Any,
    fake_channel: list[dict[str, str]],
    redis_client: redis_lib.Redis,
) -> None:
    """No oracle: the client cannot tell why a code failed."""
    never = confirm(quality, contact["id"], "mobile", "123456")
    start(quality, contact["id"], "mobile")
    deliver(worker)
    code = code_sent("mobile", contact, fake_channel)
    bad = confirm(quality, contact["id"], "mobile", wrong(code))
    for key in redis_keys(redis_client, "otp:*"):
        redis_client.delete(key)
    expired = confirm(quality, contact["id"], "mobile", code)
    assert never.status_code == bad.status_code == expired.status_code == 422
    assert (
        strip_volatile(problem(bad))
        == strip_volatile(problem(expired))
        == strip_volatile(problem(never))
    )


def test_the_fifth_attempt_can_still_succeed_but_a_sixth_cannot(
    quality: ApiClient,
    seeded: SeededTenant,
    app_engine: Engine,
    contact: dict[str, Any],
    worker: Any,
    fake_channel: list[dict[str, str]],
) -> None:
    other = make_contact(quality, contact["supplier_id"])
    for victim, wrong_attempts, expect_ok in ((contact, 4, True), (other, 5, False)):
        fake_channel.clear()
        start(quality, victim["id"], "mobile")
        deliver(worker)
        code = code_sent("mobile", victim, fake_channel)
        for _ in range(wrong_attempts):
            assert confirm(quality, victim["id"], "mobile", wrong(code)).status_code == 422
        final = confirm(quality, victim["id"], "mobile", code)
        assert (final.status_code == 200) is expect_ok, f"{wrong_attempts} wrong attempts first"
    rows = fetch_all(app_engine, seeded.id, "SELECT id, verified_mobile_at FROM supplier_contacts")
    verified = {str(r["id"]): r["verified_mobile_at"] is not None for r in rows}
    assert verified == {contact["id"]: True, other["id"]: False}


def test_after_five_wrong_attempts_a_fresh_code_can_be_requested_and_works(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    start(quality, contact["id"], "mobile")
    deliver(worker)
    first = code_sent("mobile", contact, fake_channel)
    for _ in range(5):
        confirm(quality, contact["id"], "mobile", wrong(first))
    start(quality, contact["id"], "mobile")
    deliver(worker)
    second = code_sent("mobile", contact, fake_channel)
    assert confirm(quality, contact["id"], "mobile", second).status_code == 200


def test_a_newer_code_replaces_the_older_one(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    start(quality, contact["id"], "mobile")
    deliver(worker)
    older = code_sent("mobile", contact, fake_channel)
    fake_channel.clear()
    start(quality, contact["id"], "mobile")
    deliver(worker)
    newer = code_sent("mobile", contact, fake_channel)
    if newer != older:
        assert confirm(quality, contact["id"], "mobile", older).status_code == 422
    assert confirm(quality, contact["id"], "mobile", newer).status_code == 200


def test_a_code_for_one_channel_does_not_verify_the_other(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    start(quality, contact["id"], "mobile")
    deliver(worker)
    code = code_sent("mobile", contact, fake_channel)
    assert confirm(quality, contact["id"], "email", code).status_code == 422


def test_a_code_for_one_contact_does_not_verify_another(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    other = make_contact(quality, contact["supplier_id"])
    start(quality, contact["id"], "mobile")
    deliver(worker)
    code = code_sent("mobile", contact, fake_channel)
    assert confirm(quality, other["id"], "mobile", code).status_code == 422


# --- limits and validation ----------------------------------------------------------------------------------------
def test_verify_start_is_limited_to_three_sends_per_hour_per_contact(
    quality: ApiClient, contact: dict[str, Any], worker: Any, fake_channel: list[dict[str, str]]
) -> None:
    other = make_contact(quality, contact["supplier_id"])
    statuses = [start(quality, contact["id"], "mobile").status_code for _ in range(4)]
    assert statuses[:3] == [statuses[0]] * 3 and statuses[0] in OK
    assert statuses[3] == 429
    last = start(quality, contact["id"], "mobile")
    assert last.status_code == 429 and 0 < int(last.headers["retry-after"]) <= 3600
    assert problem(last)["code"] == "rate_limited"
    deliver(worker)
    assert len([m for m in fake_channel if m["to"] == contact["mobile"]]) == 3, (
        "the refused sends sent nothing"
    )
    assert start(quality, other["id"], "mobile").status_code in OK, "the limit is per contact"


@pytest.mark.parametrize("channel", ["sms", "whatsapp", "", "MOBILE", None])
def test_verify_start_rejects_an_unknown_channel(
    quality: ApiClient, contact: dict[str, Any], channel: Any
) -> None:
    resp = quality.post(f"/contacts/{contact['id']}/verify/start", {"channel": channel})
    assert resp.status_code == 422 and problem(resp)["code"] == "validation_error"


def test_verify_start_needs_a_destination_on_that_channel(
    quality: ApiClient, fake_channel: list[dict[str, str]]
) -> None:
    supplier = make_supplier(quality)
    email_only = make_contact(quality, supplier["id"], mobile=...)
    mobile_only = make_contact(quality, supplier["id"], email=...)
    assert start(quality, email_only["id"], "mobile").status_code == 422
    assert start(quality, mobile_only["id"], "email").status_code == 422


@pytest.mark.parametrize("code", ["", "12345", "1234567", "abcdef", "12 456", None, 123456])
def test_confirm_rejects_a_code_that_is_not_six_digits(
    quality: ApiClient, contact: dict[str, Any], code: Any
) -> None:
    resp = quality.post(
        f"/contacts/{contact['id']}/verify/confirm", {"channel": "mobile", "code": code}
    )
    assert resp.status_code == 422 and problem(resp)["code"] == "validation_error"


def test_verification_is_refused_for_a_contact_of_another_tenant(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant]
) -> None:
    a, b = seeded_pair
    assert a.quality and b.quality
    foreign = make_contact(api.login_as(b.quality), make_supplier(api.login_as(b.quality))["id"])
    mine = api.login_as(a.quality)
    assert start(mine, foreign["id"], "mobile").status_code == 404
    assert confirm(mine, foreign["id"], "mobile", "123456").status_code == 404


def test_viewer_cannot_start_or_confirm_verification(
    api: ApiFactory, seeded: SeededTenant, quality: ApiClient, contact: dict[str, Any]
) -> None:
    assert seeded.viewer
    viewer = api.login_as(seeded.viewer)
    assert start(viewer, contact["id"], "mobile").status_code == 403
    assert confirm(viewer, contact["id"], "mobile", "123456").status_code == 403
