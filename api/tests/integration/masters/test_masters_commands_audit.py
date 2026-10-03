"""INV-PLT-04 for every P02 masters command: authorise, change state, write ONE activity_log row and ONE outbox event in
the same transaction (equal xmin), with actor, IP and before/after. Event names for derived events come from the
registry; the five named in the plan are asserted exactly."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx
import pytest
from sqlalchemy import Engine

from tests.factories.api import ApiClient, ApiFactory
from tests.factories.contract import load
from tests.factories.db import SeededTenant
from tests.factories.masters import (
    OK,
    contact_body,
    make_contact,
    make_customer,
    make_part,
    make_supplier,
    make_supplier_part,
    part_body,
    supplier_body,
)
from tests.integration.commands.test_command_audit_and_outbox import log_rows, outbox_rows, xmin

pytestmark = pytest.mark.integration

REASON = "Documented reason for the change"


@dataclass
class Ctx:
    quality: ApiClient
    approver: ApiClient


Result = tuple[
    httpx.Response, str, str, str, str | None
]  # response, object_type, object_id, table, exact event


@dataclass
class Case:
    name: str
    prepare: Callable[[Ctx], dict[str, Any]]
    act: Callable[[Ctx, dict[str, Any]], Result]
    creates: bool = False
    multi: bool = False  # the command legitimately touches more than one object (replace)


def nothing(_: Ctx) -> dict[str, Any]:
    return {}


def with_supplier(c: Ctx) -> dict[str, Any]:
    return {"supplier": make_supplier(c.approver)}


def with_contact(c: Ctx) -> dict[str, Any]:
    supplier = make_supplier(c.quality)
    return {"supplier": supplier, "contact": make_contact(c.quality, supplier["id"])}


def with_part(c: Ctx) -> dict[str, Any]:
    return {"part": make_part(c.quality)}


def with_customer(c: Ctx) -> dict[str, Any]:
    return {"customer": make_customer(c.quality)}


def with_customer_link(c: Ctx) -> dict[str, Any]:
    part, customer = make_part(c.quality), make_customer(c.quality)
    link = c.quality.post(
        "/customer-parts", {"customer_id": customer["id"], "part_id": part["id"]}
    ).json()
    return {"link": link, "part": part, "customer": customer}


def with_supplier_part(c: Ctx) -> dict[str, Any]:
    supplier, part = make_supplier(c.quality), make_part(c.quality)
    return {
        "supplier": supplier,
        "part": part,
        "sp": make_supplier_part(c.quality, supplier["id"], part["id"]),
    }


def post(
    client: ApiClient,
    path: str,
    body: dict[str, Any],
    otype: str,
    oid: Any,
    table: str,
    event: str | None,
) -> Result:
    return client.post(path, body), otype, str(oid), table, event


CASES = [
    Case(
        "supplier-create",
        nothing,
        lambda c, s: _created(
            c.quality.post("/suppliers", supplier_body(status="approved")),
            "supplier",
            "suppliers",
            "SUPPLIER_CREATED",
        ),
        creates=True,
    ),
    Case(
        "supplier-update",
        with_supplier,
        lambda c, s: post(
            c.quality,
            f"/suppliers/{s['supplier']['id']}/update",
            {"city": "Satara"},
            "supplier",
            s["supplier"]["id"],
            "suppliers",
            "SUPPLIER_UPDATED",
        ),
    ),
    Case(
        "supplier-archive",
        with_supplier,
        lambda c, s: post(
            c.quality,
            f"/suppliers/{s['supplier']['id']}/archive",
            {"reason": REASON},
            "supplier",
            s["supplier"]["id"],
            "suppliers",
            "SUPPLIER_ARCHIVED",
        ),
    ),
    Case(
        "supplier-change-status",
        with_supplier,
        lambda c, s: post(
            c.approver,
            f"/suppliers/{s['supplier']['id']}/change-status",
            {"status": "on_watch", "reason": REASON},
            "supplier",
            s["supplier"]["id"],
            "suppliers",
            "SUPPLIER_STATUS_CHANGED",
        ),
    ),
    Case(
        "contact-create",
        with_supplier,
        lambda c, s: _created(
            c.quality.post(f"/suppliers/{s['supplier']['id']}/contacts", contact_body()),
            "contact",
            "supplier_contacts",
            None,
        ),
        creates=True,
    ),
    Case(
        "contact-update",
        with_contact,
        lambda c, s: post(
            c.quality,
            f"/contacts/{s['contact']['id']}/update",
            {"role": "Owner"},
            "contact",
            s["contact"]["id"],
            "supplier_contacts",
            None,
        ),
    ),
    Case(
        "contact-set-quality",
        with_contact,
        lambda c, s: post(
            c.quality,
            f"/contacts/{s['contact']['id']}/set-quality-contact",
            {},
            "contact",
            s["contact"]["id"],
            "supplier_contacts",
            None,
        ),
    ),
    Case(
        "contact-disable",
        with_contact,
        lambda c, s: post(
            c.quality,
            f"/contacts/{s['contact']['id']}/disable",
            {"reason": REASON},
            "contact",
            s["contact"]["id"],
            "supplier_contacts",
            "CONTACT_DISABLED",
        ),
    ),
    Case(
        "contact-replace",
        with_contact,
        lambda c, s: post(
            c.quality,
            f"/contacts/{s['contact']['id']}/replace",
            {**contact_body(), "reason": REASON},
            "contact",
            s["contact"]["id"],
            "supplier_contacts",
            None,
        ),
        multi=True,
    ),
    Case(
        "contact-consent",
        with_contact,
        lambda c, s: post(
            c.quality,
            f"/contacts/{s['contact']['id']}/consents",
            {"channel": "email", "status": "opted_in", "source": "manual"},
            "contact",
            s["contact"]["id"],
            "supplier_contacts",
            None,
        ),
    ),
    Case(
        "customer-create",
        nothing,
        lambda c, s: _created(
            c.quality.post("/customers", {"name": "OEM", "code": "OEM-1"}),
            "customer",
            "customers",
            None,
        ),
        creates=True,
    ),
    Case(
        "customer-update",
        with_customer,
        lambda c, s: post(
            c.quality,
            f"/customers/{s['customer']['id']}/update",
            {"name": "Renamed OEM"},
            "customer",
            s["customer"]["id"],
            "customers",
            None,
        ),
    ),
    Case(
        "customer-archive",
        with_customer,
        lambda c, s: post(
            c.quality,
            f"/customers/{s['customer']['id']}/archive",
            {"reason": REASON},
            "customer",
            s["customer"]["id"],
            "customers",
            None,
        ),
    ),
    Case(
        "part-create",
        nothing,
        lambda c, s: _created(c.quality.post("/parts", part_body()), "part", "parts", None),
        creates=True,
    ),
    Case(
        "part-update",
        with_part,
        lambda c, s: post(
            c.quality,
            f"/parts/{s['part']['id']}/update",
            {"name": "Renamed"},
            "part",
            s["part"]["id"],
            "parts",
            None,
        ),
    ),
    Case(
        "part-archive",
        with_part,
        lambda c, s: post(
            c.quality,
            f"/parts/{s['part']['id']}/archive",
            {"reason": REASON},
            "part",
            s["part"]["id"],
            "parts",
            None,
        ),
    ),
    Case(
        "customer-part-create",
        lambda c: {"part": make_part(c.quality), "customer": make_customer(c.quality)},
        lambda c, s: _created(
            c.quality.post(
                "/customer-parts", {"customer_id": s["customer"]["id"], "part_id": s["part"]["id"]}
            ),
            "customer_part",
            "customer_parts",
            None,
        ),
        creates=True,
    ),
    Case(
        "customer-part-archive",
        with_customer_link,
        lambda c, s: post(
            c.quality,
            f"/customer-parts/{s['link']['id']}/archive",
            {},
            "customer_part",
            s["link"]["id"],
            "customer_parts",
            None,
        ),
    ),
    Case(
        "supplier-part-create",
        lambda c: {"supplier": make_supplier(c.quality), "part": make_part(c.quality)},
        lambda c, s: _created(
            c.quality.post(
                "/supplier-parts",
                {"supplier_id": s["supplier"]["id"], "part_id": s["part"]["id"], "ppm_target": 300},
            ),
            "supplier_part",
            "supplier_parts",
            None,
        ),
        creates=True,
    ),
    Case(
        "supplier-part-update",
        with_supplier_part,
        lambda c, s: post(
            c.quality,
            f"/supplier-parts/{s['sp']['id']}/update",
            {"ppm_target": 150},
            "supplier_part",
            s["sp"]["id"],
            "supplier_parts",
            None,
        ),
    ),
    Case(
        "supplier-part-archive",
        with_supplier_part,
        lambda c, s: post(
            c.quality,
            f"/supplier-parts/{s['sp']['id']}/archive",
            {},
            "supplier_part",
            s["sp"]["id"],
            "supplier_parts",
            None,
        ),
    ),
]


def _created(resp: httpx.Response, otype: str, table: str, event: str | None) -> Result:
    assert resp.status_code in OK, resp.text
    return resp, otype, str(resp.json()["id"]), table, event


@pytest.mark.parametrize("case", CASES, ids=lambda c: c.name)
def test_command_writes_one_activity_log_row_and_one_outbox_event_in_the_same_transaction(
    api: ApiFactory,
    seeded: SeededTenant,
    app_engine: Engine,
    clean_outbox: None,
    case: Case,
) -> None:
    assert seeded.quality and seeded.approver
    ctx = Ctx(api.login_as(seeded.quality), api.login_as(seeded.approver))
    state = case.prepare(ctx)
    logs_before = len(log_rows(app_engine, seeded.id))
    events_before = len(outbox_rows(app_engine, seeded.id))

    response, object_type, object_id, table, event = case.act(ctx, state)
    assert response.status_code in OK, f"{case.name}: {response.status_code} {response.text}"

    logs = log_rows(app_engine, seeded.id)[logs_before:]
    events = outbox_rows(app_engine, seeded.id)[events_before:]
    if case.multi:
        assert 1 <= len(logs) <= 3 and 1 <= len(events) <= 3
    else:
        assert len(logs) == 1, f"{case.name}: {[r['action'] for r in logs]}"
        assert len(events) == 1, f"{case.name}: {[e['event_type'] for e in events]}"
    mine = [r for r in logs if r["object_id"] == UUID(object_id)]
    assert mine and mine[0]["object_type"] == object_type, (
        f"{case.name}: {[(r['object_type']) for r in logs]}"
    )
    entry = mine[0]
    actor = seeded.approver if case.name == "supplier-change-status" else seeded.quality
    assert (entry["actor_type"], entry["actor_id"]) == ("user", actor.id)
    assert entry["ip"] is not None and entry["action"].startswith(f"{object_type}.")
    if case.creates:
        assert entry["before"] is None and entry["after"] is not None
    else:
        assert entry["after"] is not None
    spec = load("app.core.outbox.registry", "get")(events[0]["event_type"])
    assert spec is not None, f"{case.name}: unregistered event {events[0]['event_type']}"
    if event:
        assert any(e["event_type"] == event for e in events)
        assert spec.derived is (event != "SUPPLIER_STATUS_CHANGED")
    if not case.multi:
        business = xmin(app_engine, seeded.id, table, "id = :i", {"i": UUID(object_id)})
        assert business == xmin(
            app_engine, seeded.id, "activity_log", "id = :i", {"i": entry["id"]}
        )
        assert business == xmin(
            app_engine, seeded.id, "outbox_events", "id = :i", {"i": events[0]["id"]}
        )


NO_BODY_COMMANDS = {"contact-set-quality", "customer-part-archive", "supplier-part-archive"}


@pytest.mark.parametrize(
    "case",
    [c for c in CASES if not c.creates and c.name not in NO_BODY_COMMANDS],
    ids=lambda c: c.name,
)
def test_a_command_that_fails_validation_writes_no_audit_row_and_no_event(
    api: ApiFactory, seeded: SeededTenant, app_engine: Engine, clean_outbox: None, case: Case
) -> None:
    """The pipeline authorises first, then validates; nothing is audited for a refused command."""
    assert seeded.quality and seeded.approver
    ctx = Ctx(api.login_as(seeded.quality), api.login_as(seeded.approver))
    state = case.prepare(ctx)
    logs_before = len(log_rows(app_engine, seeded.id))
    events_before = len(outbox_rows(app_engine, seeded.id))
    paths = {
        "supplier-update": (
            "quality",
            f"/suppliers/{state.get('supplier', {}).get('id')}/update",
            {"name": ""},
        ),
        "supplier-archive": (
            "quality",
            f"/suppliers/{state.get('supplier', {}).get('id')}/archive",
            {},
        ),
        "supplier-change-status": (
            "approver",
            f"/suppliers/{state.get('supplier', {}).get('id')}/change-status",
            {"status": "on_watch"},
        ),
        "contact-update": (
            "quality",
            f"/contacts/{state.get('contact', {}).get('id')}/update",
            {"name": ""},
        ),
        "contact-disable": (
            "quality",
            f"/contacts/{state.get('contact', {}).get('id')}/disable",
            {},
        ),
        "contact-replace": (
            "quality",
            f"/contacts/{state.get('contact', {}).get('id')}/replace",
            {"reason": REASON},
        ),
        "contact-consent": (
            "quality",
            f"/contacts/{state.get('contact', {}).get('id')}/consents",
            {"channel": "x"},
        ),
        "customer-update": (
            "quality",
            f"/customers/{state.get('customer', {}).get('id')}/update",
            {"name": ""},
        ),
        "customer-archive": (
            "quality",
            f"/customers/{state.get('customer', {}).get('id')}/archive",
            {},
        ),
        "part-update": (
            "quality",
            f"/parts/{state.get('part', {}).get('id')}/update",
            {"name": ""},
        ),
        "part-archive": ("quality", f"/parts/{state.get('part', {}).get('id')}/archive", {}),
        "supplier-part-update": (
            "quality",
            f"/supplier-parts/{state.get('sp', {}).get('id')}/update",
            {"ppm_target": 0},
        ),
    }
    who, path, body = paths[case.name]
    client = ctx.quality if who == "quality" else ctx.approver
    resp = client.post(path, body)
    assert resp.status_code == 422, f"{case.name}: {resp.status_code} {resp.text}"
    assert len(log_rows(app_engine, seeded.id)) == logs_before
    assert len(outbox_rows(app_engine, seeded.id)) == events_before
