"""Blueprint 8 C2 contacts: add, edit, mark quality contact, re-verification, consent (17.3).

PII rule (ADR-019): the audit trail and outbox hold masked mobile/email only."""

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from tests.factories.api import ApiClient, new_key, problem
from tests.factories.contract import load
from tests.factories.db import SeededTenant, fetch_all, tenant_conn
from tests.factories.masters import OK, contact_body, make_contact, make_supplier, mobile
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration

CONTACT_FIELDS = {
    "id",
    "supplier_id",
    "name",
    "role",
    "mobile",
    "email",
    "is_quality_contact",
    "verified_mobile_at",
    "verified_email_at",
    "active",
    "disabled_at",
    "disabled_reason",
    "replaced_by_contact_id",
    "needs_reverification",
    "consents",
}


def set_verified(engine: Engine, tenant: UUID, contact_id: str, **cols: datetime | None) -> None:
    sets = ", ".join(f"{c} = :{c}" for c in cols)
    with tenant_conn(engine, tenant) as conn:
        conn.execute(
            text(f"UPDATE supplier_contacts SET {sets} WHERE id = :i"),
            {"i": UUID(contact_id), **cols},
        )


# =================================================================================================
# create / read
# =================================================================================================
def test_create_contact_returns_the_read_model_and_persists_it(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    assert seeded.quality
    supplier = make_supplier(quality)
    body = contact_body(name="Asha Kulkarni", role="Quality head")
    resp = quality.post(f"/suppliers/{supplier['id']}/contacts", body)
    assert resp.status_code in OK, resp.text
    data = resp.json()
    assert set(data) >= CONTACT_FIELDS
    assert (data["supplier_id"], data["name"], data["role"]) == (
        supplier["id"],
        "Asha Kulkarni",
        "Quality head",
    )
    assert (data["mobile"], data["email"]) == (body["mobile"], body["email"])
    assert (data["is_quality_contact"], data["active"]) == (False, True)
    assert data["verified_mobile_at"] is None and data["verified_email_at"] is None
    assert data["disabled_at"] is None and data["replaced_by_contact_id"] is None
    assert data["needs_reverification"] is True, "an unverified active contact needs verification"
    assert data["consents"] == []
    stored = fetch_all(
        app_engine,
        seeded.id,
        "SELECT * FROM supplier_contacts WHERE id = :i",
        {"i": UUID(data["id"])},
    )
    assert stored[0]["created_by"] == seeded.quality.id and stored[0]["tenant_id"] == seeded.id


@pytest.mark.parametrize("only", ["mobile", "email"])
def test_a_contact_needs_a_mobile_or_an_email_not_both(quality: ApiClient, only: str) -> None:
    supplier = make_supplier(quality)
    body = contact_body(**{("email" if only == "mobile" else "mobile"): ...})
    assert only in body and len(body) == 3
    resp = quality.post(f"/suppliers/{supplier['id']}/contacts", body)
    assert resp.status_code in OK, resp.text


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"mobile": ..., "email": ...}, "mobile"),
        ({"name": ""}, "name"),
        ({"name": "  "}, "name"),
        ({"mobile": "98765 43210"}, "mobile"),
        ({"mobile": "9876543210"}, "mobile"),
        ({"mobile": "+0123456789"}, "mobile"),
        ({"mobile": "+91-98765-43210"}, "mobile"),
        ({"email": "not-an-email"}, "email"),
        ({"email": "a@"}, "email"),
        ({"verified_mobile_at": "2026-01-01T00:00:00Z"}, "verified_mobile_at"),
        ({"active": False}, "active"),
        ({"is_quality_contact": "yes"}, "is_quality_contact"),
    ],
    ids=lambda v: str(v)[:30],
)
def test_create_contact_rejects_invalid_input_and_creates_nothing(
    quality: ApiClient,
    seeded: SeededTenant,
    app_engine: Engine,
    override: dict[str, Any],
    field: str,
) -> None:
    supplier = make_supplier(quality)
    resp = quality.post(f"/suppliers/{supplier['id']}/contacts", contact_body(**override))
    assert resp.status_code == 422, resp.text
    assert problem(resp)["code"] == "validation_error"
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts") == []


def test_contact_for_an_unknown_supplier_is_404(quality: ApiClient) -> None:
    make_contact(quality, make_supplier(quality)["id"])  # control: the route exists and works
    resp = quality.post("/suppliers/0198f0f0-0000-7000-8000-000000000000/contacts", contact_body())
    assert resp.status_code == 404 and problem(resp)["code"] == "not_found"


def test_contacts_are_listed_per_supplier_for_every_role_and_include_disabled_ones(
    quality: ApiClient, viewer: ApiClient
) -> None:
    supplier, other = make_supplier(quality), make_supplier(quality)
    first = make_contact(quality, supplier["id"])
    second = make_contact(quality, supplier["id"])
    make_contact(quality, other["id"])
    assert (
        quality.post(
            f"/contacts/{second['id']}/disable", {"reason": "Left the company"}
        ).status_code
        == 200
    )
    for client in (quality, viewer):
        page = client.get(f"/suppliers/{supplier['id']}/contacts").json()
        assert {c["id"]: c["active"] for c in page["items"]} == {
            first["id"]: True,
            second["id"]: False,
        }
    assert viewer.get(f"/contacts/{first['id']}").json()["id"] == first["id"]


def test_get_unknown_contact_is_404(quality: ApiClient) -> None:
    real = make_contact(quality, make_supplier(quality)["id"])
    assert quality.get(f"/contacts/{real['id']}").status_code == 200, "control: the route exists"
    resp = quality.get("/contacts/0198f0f0-0000-7000-8000-000000000000")
    assert resp.status_code == 404 and problem(resp)["code"] == "not_found"


# =================================================================================================
# update
# =================================================================================================
def test_update_contact_changes_the_sent_fields_only(quality: ApiClient) -> None:
    supplier = make_supplier(quality)
    contact = make_contact(quality, supplier["id"])
    resp = quality.post(
        f"/contacts/{contact['id']}/update", {"name": "New Name", "role": "Plant manager"}
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["name"], data["role"]) == ("New Name", "Plant manager")
    assert (data["mobile"], data["email"], data["supplier_id"]) == (
        contact["mobile"],
        contact["email"],
        supplier["id"],
    )


@pytest.mark.parametrize(
    "body",
    [
        {"active": False},
        {"verified_mobile_at": "2026-01-01T00:00:00Z"},
        {"verified_email_at": "2026-01-01T00:00:00Z"},
        {"is_quality_contact": True},
        {"disabled_reason": "x"},
        {"replaced_by_contact_id": "0198f0f0-0000-7000-8000-000000000000"},
        {"supplier_id": "0198f0f0-0000-7000-8000-000000000000"},
        {"mobile": "12345"},
        {"name": ""},
    ],
    ids=lambda b: next(iter(b)),
)
def test_update_contact_cannot_touch_lifecycle_fields_and_validates(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, body: dict[str, Any]
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    before = fetch_all(
        app_engine,
        seeded.id,
        "SELECT * FROM supplier_contacts WHERE id = :i",
        {"i": UUID(contact["id"])},
    )
    resp = quality.post(f"/contacts/{contact['id']}/update", body)
    assert resp.status_code == 422, resp.text
    after = fetch_all(
        app_engine,
        seeded.id,
        "SELECT * FROM supplier_contacts WHERE id = :i",
        {"i": UUID(contact["id"])},
    )
    assert after == before


def test_an_active_contact_cannot_be_left_without_mobile_and_email(quality: ApiClient) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"], email=...)
    resp = quality.post(f"/contacts/{contact['id']}/update", {"mobile": None})
    assert resp.status_code == 422, resp.text


def test_changing_the_mobile_number_clears_its_verification(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """Phone reassignment protection (blueprint 8 C2): a new number is a new, unverified number."""
    contact = make_contact(quality, make_supplier(quality)["id"])
    now = datetime.now(UTC)
    set_verified(
        app_engine, seeded.id, contact["id"], verified_mobile_at=now, verified_email_at=now
    )
    resp = quality.post(f"/contacts/{contact['id']}/update", {"mobile": mobile()})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["verified_mobile_at"] is None and data["needs_reverification"] is True
    assert data["verified_email_at"] is not None, "the email was not changed"
    same = quality.post(f"/contacts/{contact['id']}/update", {"role": "Owner"}).json()
    assert same["verified_email_at"] is not None


def test_changing_the_email_clears_its_verification(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    set_verified(app_engine, seeded.id, contact["id"], verified_email_at=datetime.now(UTC))
    data = quality.post(
        f"/contacts/{contact['id']}/update", {"email": "new.address@supplier.example.test"}
    ).json()
    assert data["verified_email_at"] is None


# =================================================================================================
# quality contact
# =================================================================================================
def test_set_quality_contact_marks_one_contact_per_supplier(quality: ApiClient) -> None:
    supplier, other = make_supplier(quality), make_supplier(quality)
    first, second = (make_contact(quality, supplier["id"]) for _ in range(2))
    foreign = make_contact(quality, other["id"])
    assert quality.post(f"/contacts/{foreign['id']}/set-quality-contact", {}).status_code == 200
    assert quality.post(f"/contacts/{first['id']}/set-quality-contact", {}).status_code == 200
    resp = quality.post(f"/contacts/{second['id']}/set-quality-contact", {})
    assert resp.status_code == 200 and resp.json()["is_quality_contact"] is True
    flags = {
        c["id"]: c["is_quality_contact"]
        for c in quality.get(f"/suppliers/{supplier['id']}/contacts").json()["items"]
    }
    assert flags == {first["id"]: False, second["id"]: True}, (
        "the previous quality contact is unmarked"
    )
    assert quality.get(f"/contacts/{foreign['id']}").json()["is_quality_contact"] is True, (
        "other suppliers untouched"
    )


def test_a_disabled_contact_cannot_become_the_quality_contact(quality: ApiClient) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    assert quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"}).status_code == 200
    resp = quality.post(f"/contacts/{contact['id']}/set-quality-contact", {})
    assert resp.status_code in (409, 422), resp.text


# =================================================================================================
# computed needs_reverification (blueprint 8 C2, A-111)
# =================================================================================================
@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(days=1), False),
        (timedelta(days=179), False),
        (timedelta(days=180) - timedelta(hours=1), False),
        (timedelta(days=180) + timedelta(hours=1), True),
        (timedelta(days=181), True),
        (timedelta(days=400), True),
    ],
    ids=["1d", "179d", "180d-1h", "180d+1h", "181d", "400d"],
)
def test_needs_reverification_flips_after_180_days(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, age: timedelta, expected: bool
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    set_verified(app_engine, seeded.id, contact["id"], verified_mobile_at=datetime.now(UTC) - age)
    assert quality.get(f"/contacts/{contact['id']}").json()["needs_reverification"] is expected
    listed = quality.get(f"/suppliers/{contact['supplier_id']}/contacts").json()["items"][0]
    assert listed["needs_reverification"] is expected


def test_a_never_verified_active_contact_needs_reverification_and_a_disabled_one_does_not(
    quality: ApiClient,
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    assert quality.get(f"/contacts/{contact['id']}").json()["needs_reverification"] is True
    quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"})
    assert quality.get(f"/contacts/{contact['id']}").json()["needs_reverification"] is False


def test_needs_reverification_is_computed_never_stored(owner_engine: Engine) -> None:
    with owner_engine.connect() as conn:
        cols = {
            r[0]
            for r in conn.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = 'supplier_contacts'"
                )
            )
        }
    assert {"supplier_id", "mobile", "verified_mobile_at", "verified_email_at"} <= cols, (
        "table exists"
    )
    assert "needs_reverification" not in cols


# =================================================================================================
# consent (blueprint 17.3)
# =================================================================================================
def consent(
    client: ApiClient,
    contact_id: str,
    status: str,
    channel: str = "whatsapp",
    source: str = "manual",
) -> Any:
    return client.post(
        f"/contacts/{contact_id}/consents", {"channel": channel, "status": status, "source": source}
    )


def test_consent_opt_in_is_recorded_per_contact_and_channel(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    resp = consent(quality, contact["id"], "opted_in", "whatsapp")
    assert resp.status_code in OK, resp.text
    assert consent(quality, contact["id"], "opted_in", "email").status_code in OK
    rows = fetch_all(
        app_engine,
        seeded.id,
        "SELECT channel, status, source, revoked_at FROM supplier_contacts c JOIN contact_consents k ON k.contact_id = c.id WHERE c.id = :i ORDER BY channel",
        {"i": UUID(contact["id"])},
    )
    assert [(r["channel"], r["status"], r["source"], r["revoked_at"]) for r in rows] == [
        ("email", "opted_in", "manual", None),
        ("whatsapp", "opted_in", "manual", None),
    ]
    listed = quality.get(f"/contacts/{contact['id']}").json()["consents"]
    assert {(c["channel"], c["status"]) for c in listed} == {
        ("whatsapp", "opted_in"),
        ("email", "opted_in"),
    }


def test_consent_opt_out_and_re_opt_in_keep_the_full_history(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    assert consent(quality, contact["id"], "opted_in").status_code in OK
    assert consent(quality, contact["id"], "opted_out", source="manual").status_code in OK
    mid = fetch_all(
        app_engine,
        seeded.id,
        "SELECT status, revoked_at FROM contact_consents WHERE contact_id = :i",
        {"i": UUID(contact["id"])},
    )
    assert [(r["status"], r["revoked_at"] is not None) for r in mid] == [("opted_out", True)]
    assert consent(quality, contact["id"], "opted_in").status_code in OK
    rows = fetch_all(
        app_engine,
        seeded.id,
        "SELECT status, revoked_at, consent_at FROM contact_consents WHERE contact_id = :i ORDER BY consent_at, id",
        {"i": UUID(contact["id"])},
    )
    assert [r["status"] for r in rows] == ["opted_out", "opted_in"], (
        "re-opt-in inserts a new row; history stays"
    )
    assert rows[0]["revoked_at"] is not None and rows[1]["revoked_at"] is None
    shown = quality.get(f"/contacts/{contact['id']}").json()["consents"]
    assert len(shown) == 2


def test_opting_in_twice_never_leaves_two_active_consents(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    assert consent(quality, contact["id"], "opted_in").status_code in OK
    second = consent(quality, contact["id"], "opted_in")
    assert second.status_code in (200, 201, 409, 422), second.text
    active = fetch_all(
        app_engine,
        seeded.id,
        "SELECT 1 FROM contact_consents WHERE contact_id = :i AND status = 'opted_in'",
        {"i": UUID(contact["id"])},
    )
    assert len(active) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"channel": "telegram", "status": "opted_in", "source": "manual"},
        {"channel": "whatsapp", "status": "maybe", "source": "manual"},
        {"channel": "whatsapp", "status": "opted_in", "source": "carrier_pigeon"},
        {"channel": "whatsapp", "status": "opted_in"},
        {"status": "opted_in", "source": "manual"},
        {
            "channel": "whatsapp",
            "status": "opted_in",
            "source": "manual",
            "revoked_at": "2026-01-01T00:00:00Z",
        },
    ],
)
def test_consent_rejects_invalid_input(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, body: dict[str, Any]
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    resp = quality.post(f"/contacts/{contact['id']}/consents", body)
    assert resp.status_code == 422, resp.text
    assert fetch_all(app_engine, seeded.id, "SELECT 1 FROM contact_consents") == []


# =================================================================================================
# PII in audit and outbox (ADR-019)
# =================================================================================================
def test_contact_audit_rows_hold_masked_mobile_and_email_never_the_raw_values(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    mask_mobile = load("app.core.logging", "mask_mobile")
    supplier = make_supplier(quality)
    body = contact_body(mobile="+919876543210", email="asha.kulkarni@supplier.example.test")
    contact = quality.post(f"/suppliers/{supplier['id']}/contacts", body).json()
    new_mobile = "+919123456789"
    quality.post(f"/contacts/{contact['id']}/update", {"mobile": new_mobile})
    rows = log_rows(app_engine, seeded.id, UUID(contact["id"]))
    assert len(rows) >= 2
    blob = json.dumps([[r["before"], r["after"], r["reason"]] for r in rows], default=str)
    for raw in (
        "+919876543210",
        "9876543210",
        "asha.kulkarni@supplier.example.test",
        new_mobile,
        "9123456789",
    ):
        assert raw not in blob, f"raw PII {raw} leaked into activity_log"
    assert rows[0]["after"]["mobile"] == mask_mobile("+919876543210") == "+91******3210"
    events = json.dumps(
        [e["payload"] for e in outbox_rows(app_engine, seeded.id, UUID(contact["id"]))], default=str
    )
    assert "asha.kulkarni" not in events and "9876543210" not in events


def test_contact_commands_replay_with_an_idempotency_key(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(quality)
    body, key = contact_body(), new_key()
    first = quality.post(f"/suppliers/{supplier['id']}/contacts", body, key=key)
    again = quality.post(f"/suppliers/{supplier['id']}/contacts", body, key=key)
    assert again.json() == first.json() and again.headers["idempotency-replayed"] == "true"
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts")) == 1
