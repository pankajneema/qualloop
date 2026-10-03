"""Blueprint 8 C2 / 9 C7: disable and replace a contact. Both revoke the old contact's access through an in-transaction
hook (P05 subscribes links and sessions; P02 proves the hook point), and the replaced contact keeps its history.

INV-MST-04 (hook part), INV-MST-05 (reason + hook part). Hook contract: `app.core.hooks.publish(name, session, ...)`
with names `contact.revoke_access` (session, contact_id) and `contact.replaced` (session, old_id, new_id)."""

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from app.core import hooks
from tests.factories.api import ApiClient, ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all, tenant_conn
from tests.factories.masters import OK, contact_body, make_contact, make_supplier, mobile
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows

pytestmark = pytest.mark.integration

REVOKE = "contact.revoke_access"
REPLACED = "contact.replaced"


@pytest.fixture
def isolated_hooks(monkeypatch: pytest.MonkeyPatch) -> defaultdict[str, list[Callable[..., None]]]:
    table: defaultdict[str, list[Callable[..., None]]] = defaultdict(list)
    monkeypatch.setattr(hooks, "_HOOKS", table)
    return table


def contact_row(engine: Engine, tenant: UUID, contact_id: str) -> dict[str, Any]:
    return fetch_all(
        engine, tenant, "SELECT * FROM supplier_contacts WHERE id = :i", {"i": UUID(contact_id)}
    )[0]


class Recorder:
    """A hook that records its calls and what the contact looked like from inside the command's transaction."""

    def __init__(self, engine: Engine, tenant: UUID) -> None:
        self.engine, self.tenant = engine, tenant
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.inside: list[dict[str, Any]] = []

    def hook(self, name: str) -> Callable[..., None]:
        def run(session: Any, *ids: Any) -> None:
            self.calls.append((name, tuple(str(i) for i in ids)))
            rows = session.execute(
                text(
                    "SELECT id, active, disabled_reason, replaced_by_contact_id FROM supplier_contacts WHERE id = ANY(:ids)"
                ),
                {"ids": [UUID(str(i)) for i in ids]},
            ).all()
            outside = fetch_all(
                self.engine,
                self.tenant,
                "SELECT id, active FROM supplier_contacts WHERE id = ANY(:ids)",
                {"ids": [UUID(str(i)) for i in ids]},
            )
            self.inside.append(
                {
                    "name": name,
                    "in_txn": {str(r[0]): (r[1], r[2], str(r[3]) if r[3] else None) for r in rows},
                    "outside": {str(r["id"]): r["active"] for r in outside},
                }
            )

        return run


# =================================================================================================
# disable
# =================================================================================================
def test_disable_contact_requires_reason(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    before = contact_row(app_engine, seeded.id, contact["id"])
    for body in ({}, {"reason": ""}, {"reason": "   "}, {"reason": None}, {"reason": "x" * 2001}):
        resp = quality.post(f"/contacts/{contact['id']}/disable", body)
        assert resp.status_code == 422, body
        assert any(e["field"] == "reason" for e in problem(resp)["errors"])
    assert contact_row(app_engine, seeded.id, contact["id"]) == before
    assert [
        r for r in log_rows(app_engine, seeded.id, UUID(contact["id"])) if "disable" in r["action"]
    ] == []
    assert all(
        e["event_type"] != "CONTACT_DISABLED"
        for e in outbox_rows(app_engine, seeded.id, UUID(contact["id"]))
    )


def test_disable_contact_makes_it_inactive_with_reason_and_timestamp(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    started = datetime.now(UTC)
    resp = quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left the company"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["active"], data["disabled_reason"]) == (False, "Left the company")
    assert datetime.fromisoformat(data["disabled_at"]) >= started.replace(microsecond=0)
    stored = contact_row(app_engine, seeded.id, contact["id"])
    assert stored["active"] is False and stored["disabled_reason"] == "Left the company"
    audit = [
        r for r in log_rows(app_engine, seeded.id, UUID(contact["id"])) if "disable" in r["action"]
    ]
    assert len(audit) == 1 and audit[0]["reason"] == "Left the company"
    assert audit[0]["before"]["active"] is True and audit[0]["after"]["active"] is False
    events = [
        e
        for e in outbox_rows(app_engine, seeded.id, UUID(contact["id"]))
        if e["event_type"] == "CONTACT_DISABLED"
    ]
    assert len(events) == 1


def test_disabling_a_disabled_contact_is_409_and_does_not_call_the_hook(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, isolated_hooks: Any
) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    assert quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"}).status_code == 200
    recorder = Recorder(app_engine, seeded.id)
    hooks.subscribe(REVOKE, recorder.hook(REVOKE))
    resp = quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left again"})
    assert resp.status_code == 409 and problem(resp)["code"] == "invalid_transition"
    assert recorder.calls == []


def test_disable_contact_calls_the_revocation_hook_inside_the_transaction(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, isolated_hooks: Any
) -> None:
    """INV-MST-05: the hook runs once, with the contact id, before commit (P05 revokes links and sessions there)."""
    contact = make_contact(quality, make_supplier(quality)["id"])
    recorder = Recorder(app_engine, seeded.id)
    hooks.subscribe(REVOKE, recorder.hook(REVOKE))
    assert quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"}).status_code == 200
    assert recorder.calls == [(REVOKE, (contact["id"],))]
    seen = recorder.inside[0]
    assert seen["in_txn"][contact["id"]][0] is False, (
        "the hook sees the disabled contact in the same transaction"
    )
    assert seen["outside"][contact["id"]] is True, "…which is not committed yet for anyone else"
    assert contact_row(app_engine, seeded.id, contact["id"])["active"] is False


def test_a_failing_revocation_hook_rolls_the_disable_back(
    api: ApiFactory,
    seeded: SeededTenant,
    app_engine: Engine,
    isolated_hooks: Any,
    clean_outbox: None,
) -> None:
    assert seeded.quality
    client = api.login_as(seeded.quality)
    contact = make_contact(client, make_supplier(client)["id"])
    key = new_key()

    def boom(session: Any, contact_id: Any) -> None:
        raise RuntimeError("revocation failed")

    hooks.subscribe(REVOKE, boom)
    resp = client.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"}, key=key)
    assert resp.status_code == 500 and problem(resp)["code"] == "internal_error"
    assert "revocation failed" not in resp.text
    stored = contact_row(app_engine, seeded.id, contact["id"])
    assert stored["active"] is True and stored["disabled_at"] is None
    assert [
        r for r in log_rows(app_engine, seeded.id, UUID(contact["id"])) if "disable" in r["action"]
    ] == []
    assert all(
        e["event_type"] != "CONTACT_DISABLED"
        for e in outbox_rows(app_engine, seeded.id, UUID(contact["id"]))
    )
    isolated_hooks.clear()
    assert (
        client.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"}, key=key).status_code
        == 200
    ), "the failed attempt released its idempotency key"


def test_a_rejected_disable_never_reaches_the_hook(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, isolated_hooks: Any
) -> None:
    assert seeded.quality and seeded.viewer
    quality = api.login_as(seeded.quality)
    contact = make_contact(quality, make_supplier(quality)["id"])
    recorder = Recorder(app_engine, seeded.id)
    hooks.subscribe(REVOKE, recorder.hook(REVOKE))
    assert quality.post(f"/contacts/{contact['id']}/disable", {}).status_code == 422
    assert (
        api.login_as(seeded.viewer)
        .post(f"/contacts/{contact['id']}/disable", {"reason": "x"})
        .status_code
        == 403
    )
    assert (
        quality.post(
            "/contacts/0198f0f0-0000-7000-8000-000000000000/disable", {"reason": "x"}
        ).status_code
        == 404
    )
    assert recorder.calls == []


def test_a_disabled_contact_cannot_be_updated_verified_or_given_consent(quality: ApiClient) -> None:
    contact = make_contact(quality, make_supplier(quality)["id"])
    assert quality.post(f"/contacts/{contact['id']}/disable", {"reason": "Left"}).status_code == 200
    for path, body in (
        (f"/contacts/{contact['id']}/update", {"name": "Zombie"}),
        (f"/contacts/{contact['id']}/verify/start", {"channel": "mobile"}),
        (
            f"/contacts/{contact['id']}/consents",
            {"channel": "email", "status": "opted_in", "source": "manual"},
        ),
    ):
        resp = quality.post(path, body)
        assert resp.status_code in (409, 422), f"{path}: {resp.status_code}"


# =================================================================================================
# replace
# =================================================================================================
def replacement(**over: Any) -> dict[str, Any]:
    body = contact_body(name="New Quality Head")
    body["reason"] = "Asha resigned; Ravi takes over"
    body.update(over)
    return {k: v for k, v in body.items() if v is not ...}


def test_replace_contact_creates_the_new_contact_disables_the_old_and_links_them(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    supplier = make_supplier(quality)
    old = make_contact(quality, supplier["id"], name="Asha")
    body = replacement()
    resp = quality.post(f"/contacts/{old['id']}/replace", body)
    assert resp.status_code in OK, resp.text
    new = resp.json()
    assert new["id"] != old["id"] and new["supplier_id"] == supplier["id"]
    assert (new["name"], new["mobile"], new["email"]) == (
        "New Quality Head",
        body["mobile"],
        body["email"],
    )
    assert (
        new["active"] is True
        and new["verified_mobile_at"] is None
        and new["verified_email_at"] is None
    )
    assert new["consents"] == [], "consent belongs to a person; it is not inherited"

    old_row = contact_row(app_engine, seeded.id, old["id"])
    assert old_row["active"] is False and old_row["disabled_reason"] == body["reason"]
    assert old_row["disabled_at"] is not None
    assert str(old_row["replaced_by_contact_id"]) == new["id"]
    audit = [
        r for r in log_rows(app_engine, seeded.id, UUID(old["id"])) if "replace" in r["action"]
    ]
    assert len(audit) == 1 and audit[0]["reason"] == body["reason"]
    events = outbox_rows(app_engine, seeded.id, UUID(old["id"])) + outbox_rows(
        app_engine, seeded.id, UUID(new["id"])
    )
    assert [e["event_type"] for e in events].count("CONTACT_REPLACED") == 1


def test_replaced_contact_keeps_its_history(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    """The old contact row, its verification times, consents and audit trail all survive the replacement."""
    supplier = make_supplier(quality)
    old = make_contact(quality, supplier["id"], name="Asha")
    stamp = datetime(2026, 8, 1, 9, 30, tzinfo=UTC)
    with tenant_conn(app_engine, seeded.id) as conn:
        conn.execute(
            text("UPDATE supplier_contacts SET verified_mobile_at = :t WHERE id = :i"),
            {"t": stamp, "i": UUID(old["id"])},
        )
    assert (
        quality.post(
            f"/contacts/{old['id']}/consents",
            {"channel": "whatsapp", "status": "opted_in", "source": "manual"},
        ).status_code
        in OK
    )
    trail_before = len(log_rows(app_engine, seeded.id, UUID(old["id"])))
    consents_before = quality.get(f"/contacts/{old['id']}").json()["consents"]

    assert quality.post(f"/contacts/{old['id']}/replace", replacement()).status_code in OK

    kept = quality.get(f"/contacts/{old['id']}")
    assert kept.status_code == 200
    data = kept.json()
    assert (
        data["name"] == "Asha" and data["mobile"] == old["mobile"] and data["email"] == old["email"]
    )
    assert datetime.fromisoformat(data["verified_mobile_at"]) == stamp
    assert data["consents"] == consents_before
    assert len(log_rows(app_engine, seeded.id, UUID(old["id"]))) >= trail_before + 1
    listed = quality.get(f"/suppliers/{supplier['id']}/contacts").json()["items"]
    assert {c["id"] for c in listed} >= {old["id"], data["replaced_by_contact_id"]}
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts")) == 2, (
        "nothing deleted"
    )


def test_the_quality_contact_flag_moves_to_the_replacement(quality: ApiClient) -> None:
    supplier = make_supplier(quality)
    old = make_contact(quality, supplier["id"])
    assert quality.post(f"/contacts/{old['id']}/set-quality-contact", {}).status_code == 200
    new = quality.post(f"/contacts/{old['id']}/replace", replacement()).json()
    flags = {
        c["id"]: c["is_quality_contact"]
        for c in quality.get(f"/suppliers/{supplier['id']}/contacts").json()["items"]
    }
    assert flags == {old["id"]: False, new["id"]: True}


def test_replace_contact_calls_the_revocation_and_replaced_hooks_in_the_transaction(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, isolated_hooks: Any
) -> None:
    """INV-MST-04 (hook part): revoke the OLD contact's access, and announce old -> new so P05 can reassign SCARs."""
    old = make_contact(quality, make_supplier(quality)["id"])
    recorder = Recorder(app_engine, seeded.id)
    hooks.subscribe(REVOKE, recorder.hook(REVOKE))
    hooks.subscribe(REPLACED, recorder.hook(REPLACED))
    resp = quality.post(f"/contacts/{old['id']}/replace", replacement())
    assert resp.status_code in OK, resp.text
    new_id = resp.json()["id"]
    assert sorted(recorder.calls) == sorted(
        [(REVOKE, (old["id"],)), (REPLACED, (old["id"], new_id))]
    )
    replaced_view = next(i for i in recorder.inside if i["name"] == REPLACED)
    assert new_id in replaced_view["in_txn"], "the new contact exists inside the transaction"
    assert new_id not in replaced_view["outside"], "…and is invisible outside it until commit"
    assert replaced_view["in_txn"][old["id"]][0] is False
    assert replaced_view["in_txn"][old["id"]][2] == new_id


def test_a_failing_replaced_hook_leaves_no_new_contact_and_the_old_one_active(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, isolated_hooks: Any
) -> None:
    old = make_contact(quality, make_supplier(quality)["id"])

    def boom(session: Any, old_id: Any, new_id: Any) -> None:
        raise RuntimeError("scar reassignment failed")

    hooks.subscribe(REPLACED, boom)
    resp = quality.post(f"/contacts/{old['id']}/replace", replacement())
    assert resp.status_code == 500
    rows = fetch_all(
        app_engine, seeded.id, "SELECT id, active, replaced_by_contact_id FROM supplier_contacts"
    )
    assert [(str(r["id"]), r["active"], r["replaced_by_contact_id"]) for r in rows] == [
        (old["id"], True, None)
    ]


def test_replace_requires_a_reason(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    old = make_contact(quality, make_supplier(quality)["id"])
    for reason in (..., "", "   ", None):
        body = replacement(reason=reason)
        resp = quality.post(f"/contacts/{old['id']}/replace", body)
        assert resp.status_code == 422, reason
        assert any(e["field"] == "reason" for e in problem(resp)["errors"])
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts")) == 1


@pytest.mark.parametrize("missing", [{"name": ...}, {"mobile": ..., "email": ...}])
def test_replace_requires_a_name_and_a_way_to_reach_the_new_contact(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine, missing: dict[str, Any]
) -> None:
    old = make_contact(quality, make_supplier(quality)["id"])
    resp = quality.post(f"/contacts/{old['id']}/replace", replacement(**missing))
    assert resp.status_code == 422, resp.text
    assert contact_row(app_engine, seeded.id, old["id"])["active"] is True
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts")) == 1


def test_replacing_an_already_disabled_contact_is_409(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    old = make_contact(quality, make_supplier(quality)["id"])
    assert quality.post(f"/contacts/{old['id']}/disable", {"reason": "Left"}).status_code == 200
    resp = quality.post(f"/contacts/{old['id']}/replace", replacement())
    assert resp.status_code == 409 and problem(resp)["code"] == "invalid_transition"
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts")) == 1


def test_a_contact_cannot_be_replaced_twice(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    old = make_contact(quality, make_supplier(quality)["id"])
    assert quality.post(f"/contacts/{old['id']}/replace", replacement()).status_code in OK
    again = quality.post(f"/contacts/{old['id']}/replace", replacement(mobile=mobile()))
    assert again.status_code == 409
    assert len(fetch_all(app_engine, seeded.id, "SELECT 1 FROM supplier_contacts")) == 2


def test_a_contact_cannot_be_replaced_with_itself(
    quality: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    old = make_contact(quality, make_supplier(quality)["id"])
    resp = quality.post(
        f"/contacts/{old['id']}/replace", replacement(replacement_contact_id=old["id"])
    )
    assert resp.status_code == 422, resp.text
    assert contact_row(app_engine, seeded.id, old["id"])["active"] is True


def test_replace_unknown_contact_is_404(quality: ApiClient) -> None:
    real = make_contact(quality, make_supplier(quality)["id"])
    assert quality.post(f"/contacts/{real['id']}/replace", replacement()).status_code in OK, (
        "control"
    )
    resp = quality.post("/contacts/0198f0f0-0000-7000-8000-000000000000/replace", replacement())
    assert resp.status_code == 404
