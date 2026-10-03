"""Blueprint 15.6 / 7.5: supplier status is a management decision. Only `POST /suppliers/{id}/change-status`
changes it, with a reason, by a user with `can_approve`; before and after are logged.

INV-MST-02, INV-PLT-10, API.md 2 #9 (Q+CA, reason, event SUPPLIER_STATUS_CHANGED)."""

from itertools import permutations
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory, new_key, problem
from tests.factories.db import SeededTenant, fetch_all
from tests.factories.masters import OK, STATUSES, make_supplier
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows, xmin

pytestmark = pytest.mark.integration

REASON = "Two late lots in September; moving to watch"


def supplier_row(engine: Engine, tenant: UUID, supplier_id: str) -> dict[str, Any]:
    return fetch_all(
        engine, tenant, "SELECT * FROM suppliers WHERE id = :i", {"i": UUID(supplier_id)}
    )[0]


def change(
    client: ApiClient, supplier_id: str, status: str, reason: Any = REASON, **kw: Any
) -> Any:
    body: dict[str, Any] = {"status": status}
    if reason is not ...:
        body["reason"] = reason
    return client.post(f"/suppliers/{supplier_id}/change-status", body, **kw)


# --- rejected: reason ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize("reason", [..., "", "   ", "\n\t", None, "x" * 2001, 42])
def test_change_status_without_reason_rejected(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None, reason: Any
) -> None:
    supplier = make_supplier(approver, status="approved")
    before = supplier_row(app_engine, seeded.id, supplier["id"])
    logs = len(log_rows(app_engine, seeded.id, UUID(supplier["id"])))
    events = len(outbox_rows(app_engine, seeded.id, UUID(supplier["id"])))
    resp = change(approver, supplier["id"], "on_watch", reason)
    assert resp.status_code == 422, resp.text
    body = problem(resp)
    assert body["code"] == "validation_error"
    assert any(e["field"] == "reason" for e in body["errors"]), body["errors"]
    assert supplier_row(app_engine, seeded.id, supplier["id"]) == before
    assert len(log_rows(app_engine, seeded.id, UUID(supplier["id"]))) == logs
    assert len(outbox_rows(app_engine, seeded.id, UUID(supplier["id"]))) == events


def test_reason_of_exactly_two_thousand_characters_is_accepted(approver: ApiClient) -> None:
    supplier = make_supplier(approver)
    resp = change(approver, supplier["id"], "blocked", "r" * 2000)
    assert resp.status_code == 200, resp.text


# --- rejected: can_approve ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["quality", "admin"])
def test_change_status_without_can_approve_rejected(
    api: ApiFactory,
    seeded: SeededTenant,
    approver: ApiClient,
    app_engine: Engine,
    clean_outbox: None,
    role: str,
) -> None:
    """`+CA` means the flag itself: a Quality user without it and an Admin without it are both refused."""
    user = getattr(seeded, role)
    assert user and not user.can_approve
    supplier = make_supplier(approver, status="approved")
    before = supplier_row(app_engine, seeded.id, supplier["id"])
    events = len(outbox_rows(app_engine, seeded.id, UUID(supplier["id"])))
    resp = change(api.login_as(user), supplier["id"], "blocked")
    assert resp.status_code == 403, resp.text
    assert problem(resp)["code"] == "forbidden"
    assert supplier_row(app_engine, seeded.id, supplier["id"]) == before
    assert [
        r for r in log_rows(app_engine, seeded.id, UUID(supplier["id"])) if "status" in r["action"]
    ] == []
    assert len(outbox_rows(app_engine, seeded.id, UUID(supplier["id"]))) == events


def test_authorisation_precedes_validation_so_a_forbidden_caller_learns_nothing(
    quality: ApiClient, approver: ApiClient
) -> None:
    supplier = make_supplier(approver)
    known = change(quality, supplier["id"], "not-a-status", "")
    unknown = change(quality, "0198f0f0-0000-7000-8000-000000000000", "not-a-status", "")
    assert known.status_code == unknown.status_code == 403


def test_viewer_cannot_change_a_suppliers_status(
    api: ApiFactory, seeded: SeededTenant, approver: ApiClient
) -> None:
    assert seeded.viewer
    supplier = make_supplier(approver)
    resp = change(api.login_as(seeded.viewer), supplier["id"], "blocked")
    assert resp.status_code == 403


# --- accepted -----------------------------------------------------------------------------------------------------
def test_change_status_logs_before_after(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    """INV-MST-02 / blueprint 7.5: before and after + reason are logged for every status change."""
    assert seeded.approver
    supplier = make_supplier(approver, status="approved")
    resp = change(approver, supplier["id"], "on_watch")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert (data["status"], data["status_reason"]) == ("on_watch", REASON)
    assert data["status_changed_by"] == str(seeded.approver.id) and data["status_changed_at"]

    audit = [
        r for r in log_rows(app_engine, seeded.id, UUID(supplier["id"])) if "status" in r["action"]
    ]
    assert len(audit) == 1
    entry = audit[0]
    assert entry["object_type"] == "supplier" and entry["reason"] == REASON
    assert entry["actor_type"] == "user" and entry["actor_id"] == seeded.approver.id
    assert entry["ip"] is not None
    assert entry["before"]["status"] == "approved"
    assert entry["after"]["status"] == "on_watch"
    assert entry["after"]["status_reason"] == REASON
    assert entry["after"]["status_changed_by"] == str(seeded.approver.id)

    stored = supplier_row(app_engine, seeded.id, supplier["id"])
    assert (stored["status"], stored["status_reason"], stored["status_changed_by"]) == (
        "on_watch",
        REASON,
        seeded.approver.id,
    )
    assert stored["status_changed_at"] is not None


def test_change_status_emits_exactly_one_supplier_status_changed_event(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    supplier = make_supplier(approver)
    clean = len(outbox_rows(app_engine, seeded.id, UUID(supplier["id"])))
    assert change(approver, supplier["id"], "blocked").status_code == 200
    events = outbox_rows(app_engine, seeded.id, UUID(supplier["id"]))[clean:]
    assert [(e["event_type"], e["aggregate_type"]) for e in events] == [
        ("SUPPLIER_STATUS_CHANGED", "supplier")
    ]
    assert REASON not in str(events[0]["payload"]), "payloads carry ids, not free text"


def test_status_change_business_audit_and_outbox_rows_commit_together(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    supplier = make_supplier(approver)
    sid = UUID(supplier["id"])
    assert change(approver, supplier["id"], "blocked").status_code == 200
    audit = next(r for r in log_rows(app_engine, seeded.id, sid) if "status" in r["action"])
    event = next(
        e
        for e in outbox_rows(app_engine, seeded.id, sid)
        if e["event_type"] == "SUPPLIER_STATUS_CHANGED"
    )
    business = xmin(app_engine, seeded.id, "suppliers", "id = :i", {"i": sid})
    assert business == xmin(app_engine, seeded.id, "activity_log", "id = :i", {"i": audit["id"]})
    assert business == xmin(app_engine, seeded.id, "outbox_events", "id = :i", {"i": event["id"]})


def test_change_status_to_the_current_status_is_409_invalid_transition(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine, clean_outbox: None
) -> None:
    supplier = make_supplier(approver, status="on_watch")
    resp = change(approver, supplier["id"], "on_watch")
    assert resp.status_code == 409 and problem(resp)["code"] == "invalid_transition"
    assert "on_watch" in problem(resp)["detail"].lower().replace(" ", "_")
    assert [
        r for r in log_rows(app_engine, seeded.id, UUID(supplier["id"])) if "status" in r["action"]
    ] == []


@pytest.mark.parametrize("status", ["suspended", "APPROVED", "Approved", "", None, 3, "approved "])
def test_change_status_rejects_values_outside_the_five(approver: ApiClient, status: Any) -> None:
    supplier = make_supplier(approver, status="on_watch")
    resp = change(approver, supplier["id"], status)
    assert resp.status_code == 422 and problem(resp)["code"] == "validation_error"
    assert any(e["field"] == "status" for e in problem(resp)["errors"])


@pytest.mark.parametrize(("source", "target"), list(permutations(STATUSES, 2)))
def test_every_status_can_move_to_every_other_status_with_a_reason(
    approver: ApiClient, source: str, target: str
) -> None:
    """The blueprint puts no ordering on the five management statuses (15.6), so any change is allowed."""
    supplier = make_supplier(approver, status=source)
    resp = change(approver, supplier["id"], target)
    assert resp.status_code == 200, f"{source} -> {target}: {resp.text}"
    assert resp.json()["status"] == target


def test_change_status_on_an_unknown_or_foreign_supplier_is_404(
    api: ApiFactory, seeded_pair: tuple[SeededTenant, SeededTenant], app_engine: Engine
) -> None:
    a, b = seeded_pair
    assert a.approver and b.approver
    foreign = make_supplier(api.login_as(b.approver), status="approved")
    mine = api.login_as(a.approver)
    for target in (foreign["id"], "0198f0f0-0000-7000-8000-000000000000"):
        resp = change(mine, target, "blocked")
        assert resp.status_code == 404 and problem(resp)["code"] == "not_found"
    assert supplier_row(app_engine, b.id, foreign["id"])["status"] == "approved"


def test_change_status_replays_for_the_same_idempotency_key_and_logs_once(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(approver)
    key = new_key()
    first = change(approver, supplier["id"], "blocked", key=key)
    again = change(approver, supplier["id"], "blocked", key=key)
    assert first.status_code in OK and again.status_code == first.status_code
    assert again.headers["idempotency-replayed"] == "true"
    audit = [
        r for r in log_rows(app_engine, seeded.id, UUID(supplier["id"])) if "status" in r["action"]
    ]
    assert len(audit) == 1


def test_inactive_status_is_not_an_archive(
    approver: ApiClient, seeded: SeededTenant, app_engine: Engine
) -> None:
    supplier = make_supplier(approver)
    assert change(approver, supplier["id"], "inactive").status_code == 200
    stored = supplier_row(app_engine, seeded.id, supplier["id"])
    assert stored["archived_at"] is None, "inactive is a status; archiving is a separate command"
